from copy import deepcopy
import logging
import os
from threading import Semaphore, Lock

_LOGGER = logging.getLogger("sisyphus")

def ensure_dir(name):
    try:
        os.makedirs(name)
    except Exception:
        pass
    if not os.path.isdir(name):
        raise Exception("Couldn't create test output directory '%s'" % (name,))


class Environment(dict):
    """Environment objects track settings in the testsuite. The settings are
    normal python attributes. The class just provides some convenience
    functions for constructing/merging configurations."""
    def __init__(self, **kwargs):
        dict.__init__(self)
        self.merge(kwargs)
        self.disable_override = False

    def set(self, **kwargs):
        self.merge(kwargs)

    def merge(self, mutable_set):
        for (key, value) in mutable_set.iteritems():
            self[key] = value

    def __getattr__(self, name):
        if name in self:
            return self[name]
        raise AttributeError("Environment has no attribute '%s'" % name)
    def __setattr__(self, name, value):
        if name in self and self.disable_override:
            raise Exception("Overriding disabled for environment")
        self[name] = value
    def __delattr__(self, name):
        if name in self:
            del self[name]
        raise AttributeError()

class TestStep(object):
    def __init__(self, name, func, cpu_exclusive, allow_retries):
        self.name   = name
        self.func   = func
        self.checks = []
        self.before = lambda env: None
        self.cpu_exclusive = cpu_exclusive
        self.allow_retries = allow_retries

    def set_before(func):
        """Set a function to execute right before step is executed.
        The functions gets the environment as its single argument."""
        self.before = func

    def add_check(self, check):
        self.checks.append(check)

    def add_checks(self, checks):
        self.checks += checks

    def execute(self, test_id, env, expect_success):
        retry = 1
        while retry < self.allow_retries+1:
            with CPULock(self.cpu_exclusive):
                self.before(env)
                stepresult = self.func(env)
                _LOGGER.debug("%s: step %s finished, now checking" %
                        (test_id, self.name))
                if stepresult is None:
                    _LOGGER.error("%s: stepresult of '%s' is None" %
                            (test_id, self.name))
                    return stepresult
                if stepresult.fail():
                    if not expect_success:
                        return stepresult
                    _LOGGER.warn("%s: step %s failed at try %d of %d" %\
                        (test_id, self.name, retry, self.allow_retries))
                    retry += 1
                    continue
                # if stepresult is fine, use checks
                for check in self.checks:
                    check(stepresult)
                    if stepresult.fail():
                        if not expect_success:
                            return stepresult
                        _LOGGER.warn("%s: step %s failed check at try %d of %d" %\
                            (test_id, self.name, retry, self.allow_retries))
                        break
                # return if all succeeded
                if not stepresult.fail():
                    return stepresult
                # otherwise a check failed
                _LOGGER.debug("%s: step %s check fail: %s" %
                        (test_id, self.name, stepresult.fail()))
                if not expect_success:
                    return stepresult
                retry += 1
        return stepresult

_CPULOCK_WRT = Semaphore()
_CPULOCK_MUTEX = Lock()
_CPULOCK_READCOUNT = 0

class CPULock:
    """Intra-process mechanism for exclusive CPU (all cores) use.
    Any number of exclusive==False threads may acquire this in parallel,
    but only one exclusive==True thread at any time.
    Lock state is global for all object instances,
    only the exclusive flag is object specific."""

    # Basically an implementation of the readers-writers-problem,
    # where exclusive==True means writer.
    # This implements a variant with writer-starvation,
    # because that should result in batch processing behavior in sisyphus.

    def __init__(self, exclusive):
        self.exclusive = exclusive

    def acquire(self):
        if self.exclusive: # writer
            _CPULOCK_WRT.acquire()
        else: # reader
            with _CPULOCK_MUTEX:
                global _CPULOCK_READCOUNT
                _CPULOCK_READCOUNT += 1
                if (_CPULOCK_READCOUNT == 1):
                    _CPULOCK_WRT.acquire()

    def release(self):
        if self.exclusive: # writer
            _CPULOCK_WRT.release()
        else: # reader
            with _CPULOCK_MUTEX:
                global _CPULOCK_READCOUNT
                _CPULOCK_READCOUNT -= 1
                if (_CPULOCK_READCOUNT == 0):
                    _CPULOCK_WRT.release()

    # for the with-statement:
    def __enter__(self):
        self.acquire()
    def __exit__(self, type, value, traceback):
        self.release()

class Test(object):
    """The default Test which executes a list of steps and checks."""
    def __init__(self, id):
        self.id          = id
        self.steps       = []
        self.environment = Environment(testname = id)

    def add_step(self, name, step_func=None, checks=[], cpu_exclusive=False, allow_retries=1):
        # actually name can be None, but not step_func
        # for backwards compatibility, here comes the workaround
        if step_func == None:
            step_func = name
            name = None
        if not name:
            if hasattr(step_func, "__step_name"):
                name = getattr(step_func, "__step_name")
            else:
                name = step_func.__name__
                if name.startswith("step_"):
                    name = name[5:]
        step = TestStep(name, step_func, cpu_exclusive, allow_retries)
        self.steps.append(step)
        step.add_checks(checks)
        return step

    def prepend_step(self, name, step_func, checks=[], cpu_exclusive=False, allow_retries=1):
        step = TestStep(name, step_func, cpu_exclusive, allow_retries)
        self.steps.insert(0, step)
        step.add_checks(checks)
        return step

    def run(self, expect_result):
        self.stdout = ""
        self.stderr = ""
        self.success     = True
        self.result      = "ok"
        self.stepresults = dict()
        expect_success = expect_result == self.result
        # Execute steps
        for step in self.steps:
            stepresult = step.execute(self.id, self.environment, expect_success)
            self.stepresults[step.name] = stepresult
            if stepresult.fail():
                self.success = False
                self.result  = "%s: %s" % (step.name, stepresult.error)
                self.stdout = stepresult.stdout
                self.stderr = stepresult.stderr
                break
        _LOGGER.debug("%s: all steps finished: %s" % (self.id, self.result))
