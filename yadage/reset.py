import yadage.backends.packtivity_celery
import yadage.yadagemodels
import yadage.backends.celeryapp
import json

def load_state(statefile):
    backend = yadage.backends.packtivity_celery.PacktivityCeleryBackend(
        yadage.backends.celeryapp.app
    )

    workflow = yadage.yadagemodels.YadageWorkflow.fromJSON(
        json.load(open(statefile)),
        yadage.backends.packtivity_celery.PacktivityCeleryProxy,
        backend
    )
    return workflow

import jsonpointer
import shutil
import os
import networkx as nx
import adage.visualize as av

def select_rule(workflow,offset,name):
    for x in workflow.applied_rules:
        if x.offset == offset and x.rule.name == name:
            return x
    raise RuntimeError('rule not found')

def stepsofrule(workflow,offset,name):
    rule = select_rule(workflow,offset,name)
    path = '/'.join([rule.offset,rule.rule.name])
    p = jsonpointer.JsonPointer(path)
    return rule,[x['_nodeid'] for x in p.resolve(workflow.stepsbystage)]

def reset_node_state(node):
    node.submit_time = None
    node.ready_by_time = None
    node.resultproxy = None
    node.backend = None

def reset_step(workflow,step):
    s = workflow.dag.getNode(step)
    reset_node_state(s)
    try:
        for rw in s.task.context['readwrite']:
            shutil.rmtree(rw)
            os.makedirs(rw)
    except AttributeError:
        pass

def reset_steps(workflow,steps):
    for s in steps: reset_step(workflow,s)

def collective_downstream(workflow,steps):
    downstream = set()
    for step in steps:
        for x in nx.descendants(workflow.dag,step):
            downstream.add(x)
    return list(downstream)

def reset_state(workflow,offset,name):
    rule, steps = stepsofrule(workflow,offset,name)
    toreset = steps + collective_downstream(workflow,steps)
    reset_steps(workflow,toreset)