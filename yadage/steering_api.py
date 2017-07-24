from contextlib import contextmanager
import logging
import importlib
import interactive
import yadageschemas
import os

from steering_object import YadageSteering
from utils import setupbackend_fromstring

log = logging.getLogger(__name__)

RC_FAILED = 1
RC_SUCCEEDED = 0


def run_workflow(*args, **kwargs):
    '''
    Main entry point to run a Yadage workflow
    '''
    # let's be conservative and just assume we're going to fail. will set
    # success RC explicityly
    return_value = RC_FAILED
    try:
        with steering_ctx(*args, **kwargs):
            pass
        return_value = RC_SUCCEEDED
    except:
        log.exception('Unfortunately we failed. :(')
    return return_value

@contextmanager
def steering_ctx(
    workdir,
    workflow,
    initdata = None,
    loadtoplevel = os.getcwd(),
    backend = setupbackend_fromstring('multiproc:auto'),
    cacheconfigstring = None,
    read = None,
    initdir = None,
    updateinterval = 0.02,
    loginterval = 30,
    schemadir = yadageschemas.schemadir,
    metadir = None,
    user_interaction=False,
    validate=True,
    doviz=True,
    accept_existing_workdir = False,
    statesetup = 'inmem'):
    '''
    context manage around yadage steering object.

    param workdir: work directory of workflow
    param workflow: workflow spec source
    '''

    ys = YadageSteering()

    if cacheconfigstring:
        accept_existing_workdir = True

    ys.prepare_workdir(workdir, accept_existing_workdir, stateinit = read, metadir = metadir)
    ys.init_workflow(workflow, loadtoplevel, initdata,
        statesetup = statesetup,
        initdir = initdir,
        validate = validate,
        schemadir = schemadir)
    
    custom_tracker = os.environ.get('YADAGE_CUSTOM_TRACKER',None)
    if custom_tracker:
        modulename,trackerclassname = custom_tracker.split(':')
        module = importlib.import_module(modulename)
        trackerclass = getattr(module,trackerclassname)
        ys.adage_argument(additional_trackers = [trackerclass()])

    ys.adage_argument(
        default_trackers = doviz,
        trackevery = loginterval,
        update_interval = updateinterval,
        workdir='{}/adage'.format(ys.metadir)
    )
    if user_interaction:
        extend, submit = interactive.interactive_deciders()
        ys.adage_argument(
            extend_decider = extend,
            submit_decider = submit
        )
    yield ys

    log.info('running yadage workflow %s on backend %s', workflow, backend)
    if cacheconfigstring:
        if cacheconfigstring == 'checksums':
            backend.enable_cache(':'.join([cacheconfigstring,os.path.join(ys.metadir,'cache.json')]))
        else:
            backend.enable_cache(cacheconfigstring)

    try:
        ys.run_adage(backend)
    finally:
        ys.serialize()
    if doviz:
        ys.visualize()

