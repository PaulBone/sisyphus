"""
Convenience function
Alternative to subprocess and os.system
"""
import subprocess
import resource
import sys
import signal

_EXIT_CODES = dict((-k, v) for v, k in signal.__dict__.items() if v.startswith('SIG'))
del _EXIT_CODES[0]


class SigKill(Exception):
    def __init__(self, retcode, name):
        self.retcode = retcode
        self.name = name


def lower_rlimit(res, limit):
    (soft, hard) = resource.getrlimit(res)
    if soft > limit or soft == resource.RLIM_INFINITY:
        soft = limit
    if hard > limit or hard == resource.RLIM_INFINITY:
        hard = limit
    resource.setrlimit(res, (soft, hard))


def set_rlimit(timeout):
    if timeout > 0.0:
        lower_rlimit(resource.RLIMIT_CPU, timeout)
    MB = 1024 * 1024
    lower_rlimit(resource.RLIMIT_CORE,  0)
    lower_rlimit(resource.RLIMIT_DATA,  1024 * MB)
    lower_rlimit(resource.RLIMIT_STACK, 1024 * MB)
    lower_rlimit(resource.RLIMIT_FSIZE,   32 * MB)


def execute(cmd, env=None, timeout=0):
    """Execute a command and return stderr and stdout data"""

    cmd = filter(lambda x: x, cmd.split(' '))
    proc = subprocess.Popen(cmd,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            preexec_fn=lambda: set_rlimit(timeout),
                            env=env)
    out, err = proc.communicate()
    returncode = proc.returncode
    # Usually python can recognize application terminations triggered by
    # signals, but somehow it doesn't do this for java (I suspect, that java
    # catches the signals itself but then shuts down more 'cleanly' than it
    # should. Calculate to python convention returncode
    if returncode > 127:
        returncode = 128 - returncode
    if returncode in _EXIT_CODES:
        raise SigKill(returncode, _EXIT_CODES[returncode])
    return (out, err, returncode)


if __name__ == "__main__":
    out, err, retcode = execute("hostname")
    print (out)
