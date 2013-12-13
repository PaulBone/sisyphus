"""Helper functions to create testsets based on a list of filename patterns
with associated test factories."""
from glob import iglob
import logging
import os
import sys
import traceback

_LOGGER = logging.getLogger("sisyphus")

def _make_test(filename, factories):
    """Given a filename create a new Test object"""
    # Determine Tester to be used
    factory = None
    for (test, tfactory) in factories:
        if test(filename):
            factory = tfactory
            break
    if factory is None:
        _LOGGER.info("Couldn't determine Test factory for '%s'" % filename)
        return None

    try:
        test = factory(filename)
    except Exception as e:
        (_, _, tb) = sys.exc_info()
        _LOGGER.warning("Couldn't create test '%s': %s" % (filename, e), exc_info=True)
        return None
    if test is None:
        _LOGGER.warning("Factory returned None for test '%s'" % filename)
        return None
    if not hasattr(test, 'run'):
        _LOGGER.warning("Factory created invalid test for '%s': test object has no run method" % (filename))
        return None

    return test


def _make_tests_from_dir(directory, factories):
    names = []
    tests = []
    for name in iglob(directory+"/*"):
        test = _make_test(name, factories)
        if test:
            tests.append(test)
    return tests


def create_tests(dirs, factories):
    tests = []
    for d in dirs:
        tests += _make_tests_from_dir(d, factories)
    return tests
