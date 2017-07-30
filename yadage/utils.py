import json
import yaml
import os
import click
import zipfile
import urllib2
import logging
import jsonpointer
import jq
import hashlib
import uuid
import jsonref
import copy
import glob2 as glob
import importlib

from tasks import outputReference
from backends.trivialbackend import TrivialProxy, TrivialBackend

log = logging.getLogger(__name__)

def set_backend(dag, backend, proxymaker):
    '''
    sets backend and proxies for each node in the DAG.
    proxymaker is a 1-ary function that takes the node object and
    returns a suitable result proxy
    '''
    for nodename in dag.nodes():
        n = dag.getNode(nodename)
        n.backend = backend
        n.resultproxy = proxymaker(n)


def set_trivial_backend(dag, jsondata):
    '''
    sets the backend for the case of a static backend
    Proxies are set using the node identifier
    '''
    backend = TrivialBackend()
    set_backend(
        dag,
        backend,
        proxymaker=lambda n: TrivialProxy(
            status=jsondata[n.identifier]['status'],
            result=jsondata[n.identifier]['result']
        )
    )
    return backend


DEFAULT_ID_METHOD = 'jsonhash'


def json_hash(jsonable):
    # log.info('hashing: %s',json.dumps(jsonable, cls=WithJsonRefEncoder, sort_keys=True))
    the_hash  = hashlib.sha1(json.dumps(jsonable, cls=WithJsonRefEncoder, sort_keys=True)).hexdigest()
    # log.info('got %s',hash)
    return the_hash


def get_id_fromjson(jsonobject, method = DEFAULT_ID_METHOD):
    method = os.environ.get('YADAGE_ID_METHOD', method)
    if method == 'uuid':
        return str(uuid.uuid1())
    elif method == 'jsonhash':
        return json_hash(jsonobject)
    else:
        raise NotImplementedError(
            'unkown id generation method {}'.format(method))

def get_obj_id(obj_with_json_method, method = DEFAULT_ID_METHOD):
    return get_id_fromjson(obj_with_json_method.json(), method)


class WithJsonRefEncoder(json.JSONEncoder):

    def default(self, obj):
        if isinstance(obj, jsonref.JsonRef):
            return {k: v for k, v in obj.iteritems()}
        try:
            super(WithJsonRefEncoder, self).default(obj)
        except TypeError:
            return obj.json()

def process_refs(x, dag):
    if type(x) == dict:
        for k, v in x.iteritems():
            x[k] = process_refs(v, dag)
        return x
    elif type(x) == list:
        for i, e in enumerate(x):
            x[i] = process_refs(e, dag)
        return x
    elif type(x) == outputReference:
        return x.pointer.resolve(dag.getNode(x.stepid).result)
    else:
        return x

def leaf_iterator(jsonable):
    '''
    generator function to yield leafs items of a JSON-like structure alongside
    their position in the structure as determined by a JSONPointer.
    
    :return: tuples (jsonpointer, leaf value)
    '''
    allleafs = jq.jq('leaf_paths').transform(jsonable, multiple_output = True)
    leafpointers = [jsonpointer.JsonPointer.from_parts(x) for x in allleafs]
    for x in leafpointers:
        yield x,x.get(jsonable)

def leaf_iterator_jsonlike(jsonlike, path = None):
    ''''
    :param jsonlike: a jsonlike object (i.e. nested lists/arrays: leaf-types must not be JSONable)
    :return: iterator that yields (JSON path, leaf value) tuples
    '''
    path = path or []
    if type(jsonlike) == list:
        for i,x in enumerate(jsonlike):
            thispath = copy.deepcopy(path)
            thispath.append(i)
            for leaf in leaf_iterator_jsonlike(x, path = thispath):
                yield leaf
    elif type(jsonlike) == dict:
        for k,v in jsonlike.iteritems():
            thispath = copy.deepcopy(path)
            thispath.append(k)
            for leaf in leaf_iterator_jsonlike(v, path = thispath):
                yield leaf
    else:
        yield jsonpointer.JsonPointer.from_parts(path),jsonlike


def discover_initfiles(initdata,sourcedir):
    '''inspect sourcedir, first tries exact path match, and then (possbly recursive) glob'''
    log.info('inspecting %s to discover referenced input files',sourcedir)

    # filled_initdata = copy.deepcopy(initdata)
    for pointer,value in leaf_iterator(initdata):
        if type(value) not in [str,unicode]: continue
        within_sourcedir = os.path.join(sourcedir,value)
        globresult = glob.glob(os.path.join(sourcedir,value))
        if os.path.exists(within_sourcedir):
            pointer.set(initdata,within_sourcedir)
        elif globresult:
            pointer.set(initdata,globresult)
    return initdata

def getdata_options(dataopts):
    dataoptdict = {}
    for x in dataopts:
        key, value = x.split('=')
        dataoptdict[key] = yaml.load(value)
    return dataoptdict

def getinit_data(initfiles, parameters):
    '''
    get initial data from both a list of files and a list of 'pname=pvalue'
    strings as they are passed in the command line <pvalue> is assumed to be a
    YAML parsable string.
    '''

    initdata = {}
    for initfile in initfiles:
        log.info('loading initialization data from file %s',initfile)
        initdata.update(**yaml.load(open(initfile)))

    for x in parameters:
        key, value = x.split('=')
        initdata[key] = yaml.load(value)
    return initdata

def prepare_workdir_from_archive(initdir, inputarchive):
    if os.path.exists(initdir):
        raise click.exceptions.ClickException(click.style(
            "initialization directory exists and input archive give. Can't have both", fg='red'))
    os.makedirs(initdir)
    localzipfile = '{}/.yadage_inputarchive.zip'.format(initdir)
    f = urllib2.urlopen(inputarchive)
    with open(localzipfile,'w') as lf:
        lf.write(f.read())
    with zipfile.ZipFile(localzipfile) as zf:
        zf.extractall(path=initdir)
    os.remove(localzipfile)
    return initdir

def setupbackend_fromstring(backend, name = 'backendname'):
    import backends.packtivitybackend as pb
    return pb.PacktivityBackend(packtivity_backendstring = backend)

def setupstateprovider(datatype,dataarg,dataopts):
    if datatype == 'fromenv':
        module = importlib.import_module(os.environ['PACKTIVITY_STATEPROVIDER'])
        return module.setup_provider(dataarg,dataopts)
    raise RuntimeError('unknown data type %s', datatype)
