import logging
import sys
try:
    import gv
except ImportError:
    sys.path.append('/usr/lib/pyshared/python2.6')
    import gv

from copy import deepcopy

from pygraph.algorithms.cycles import find_cycle
from pygraph.classes.digraph import digraph
from pygraph.readwrite.dot import write

from pyplete import PyPlete

from django_detect_cyclic.utils import get_applications

CYCLE_COLOR_SEED = "f8c85c"
CYCLE_LABEL = 'Cycle'
log = logging.getLogger('django_detect_cyclic.graph_utils.py')


def create_graph_test(*args, **kwargs):
    gr = digraph()
    gr.add_nodes(["Portugal", "Spain", "France", "Germany", "Belgium", "Netherlands", "Italy"])
    gr.add_node_attribute("Spain", ("style", "filled"))
    gr.add_node_attribute("Spain", ("fillcolor", "red"))
    gr.add_node_attribute("Spain", ("color", "blue"))
    gr.add_node_attribute("Spain", ("fontcolor", "yellow"))
    gr.add_edge(("Portugal", "Spain"))
    gr.add_edge(("Spain", "France"))
    gr.add_edge(("France", "Portugal"))
    gr.add_edge(("France", "Belgium"))
    gr.add_edge(("France", "Germany"))
    gr.add_edge(("Germany", "France"))
    gr.add_edge(("France", "Italy"))
    gr.add_edge(("Italy", "Belgium"))
    gr.add_edge(("Belgium", "France"))
    gr.add_edge(("Belgium", "Netherlands"))
    gr.add_edge(("Germany", "Belgium"))
    gr.add_edge(("Germany", "Netherlands"))
    return gr


def create_graph(include_apps=None, exclude_apps=None, exclude_packages=None, verbosity=False,
                 show_modules=False):
    gr = digraph()
    applications = get_applications(include_apps, exclude_apps)
    if not show_modules:
        gr.add_nodes(applications)
    pyplete = PyPlete()
    for app_source in applications:
        if verbosity:
            log.info("Analizing %s" % app_source)
        _add_edges_to_package(gr, app_source, app_source, applications, pyplete, exclude_packages, show_modules, verbosity)
    return gr


def treatment_final_graph(gr, remove_isolated_nodes=False, remove_sink_nodes=False,
                          remove_source_nodes=False, only_cyclic=False, verbosity=False):
    if only_cyclic:
        for edge, properties in gr.edge_properties.items():
            if not CYCLE_LABEL in properties['label']:
                if verbosity:
                    log.info("Remove the edge %s-->%s" % edge)
                gr.del_edge(edge)
    if remove_source_nodes:
        for node, incidence in gr.node_incidence.items():
            if not incidence:
                if verbosity:
                    log.info("Remove the node %s" % node)
                gr.del_node(node)
    if remove_sink_nodes:
        for node, neighbor in gr.node_neighbors.items():
            if not neighbor:
                if verbosity:
                    log.info("Remove the node %s" % node)
                gr.del_node(node)
    if remove_isolated_nodes:
        for node, incidence in gr.node_incidence.items():
            neighbor = gr.node_neighbors.get(node, None)
            if not incidence and not neighbor:
                if verbosity:
                    log.info("Remove the node %s" % node)
                gr.del_node(node)
    return gr


def _add_edges_to_package(gr, package, app_source, applications, pyplete=None, exclude_packages=None, show_modules=False, verbosity=False):
    pyplete = pyplete or PyPlete()
    package_modules = package.split(".")
    importables_to_app = []
    pyplete.get_importables_rest_level(importables_to_app, package_modules[0], package_modules[1:], into_module=False)
    for importable_to_app, importable_type  in importables_to_app:
        if importable_type == 'package':
            if exclude_packages and importable_to_app in exclude_packages:
                if verbosity:
                    log.info('\t Ignore %s' % importable_to_app)
                continue
            subpackage = '%s.%s' % (package, importable_to_app)
            if subpackage not in applications:
                _add_edges_to_package(gr, subpackage, app_source, applications, pyplete,
                                      exclude_packages=exclude_packages,
                                      show_modules=show_modules,
                                      verbosity=verbosity)
        if importable_type != 'module':
            continue
        if show_modules:
            node = package_modules + [importable_to_app]
            if not gr.has_node('.'.join(node)):
                gr.add_node('.'.join(node))
        code = pyplete.get_imp_loader_from_path(package_modules[0], package_modules[1:] + [importable_to_app])[0].get_source()
        try:
            imports_code = pyplete.get_pysmell_modules_to_text(code)['POINTERS']
        except SyntaxError, e:
            if verbosity:
                log.error("\t File: %s SyntaxError %s" % (package_modules + [importable_to_app], e))
            continue
        if show_modules:
            for import_code in imports_code.values():
                import_module = _get_module_to_import(import_code.split('.'), pyplete=pyplete)
                import_module_is_into_app = False
                if import_module:
                    for app in applications:
                        if import_module.startswith(app):
                            import_module_is_into_app = True
                            break
                    if import_module_is_into_app:
                        if not gr.has_node(import_module):
                            gr.add_node(import_module)
                        node_source = '.'.join(node)
                        if not gr.has_edge((node_source, import_module)):
                            if verbosity:
                                log.info('\t %s --> %s' % (node_source, import_module))
                            gr.add_edge((node_source, import_module))
                            gr.set_edge_label((node_source, import_module), "(1)")
                        else:
                            weight = gr.edge_weight((node_source, import_module))
                            gr.set_edge_weight((node_source, import_module), weight + 1)
                            gr.set_edge_label((node_source, import_module), "(%s)" % weight)

        else:
            for import_code in imports_code.values():
                if not import_code.startswith(app_source):
                    for app_destination in applications:
                        if import_code.startswith(app_destination):
                            if not gr.has_edge((app_source, app_destination)):
                                if verbosity:
                                    log.info('\t %s --> %s' % (app_source, app_destination))
                                gr.add_edge((app_source, app_destination))
                                gr.set_edge_label((app_source, app_destination), "(1)")
                            else:
                                weight = gr.edge_weight((app_source, app_destination))
                                gr.set_edge_weight((app_source, app_destination), weight + 1)
                                gr.set_edge_label((app_source, app_destination), "(%s)" % weight)
                            break


def _get_module_to_import(import_code, pyplete=None):
    if len(import_code) == 0:
        return None
    pyplete = pyplete or PyPlete()
    imports = []
    pyplete.get_importables_rest_level(imports, import_code[0], import_code[1:])
    if imports:
        return '.'.join(import_code)
    return _get_module_to_import(import_code[:-1], pyplete=pyplete)


def find_all_cycle(gr, gr_copy=None, number_cycle=1):
    gr_copy = gr_copy or deepcopy(gr)
    cycle = find_cycle(gr_copy)
    if cycle:
        mark_cycle(gr, cycle, number_cycle, gr_copy)
        find_all_cycle(gr, gr_copy, number_cycle=number_cycle + 1)


def mark_cycle(gr, cycle, number_cycle, gr_copy):
    i = 0
    while i < len(cycle):
        item = cycle[i]
        try:
            next_item = cycle[i + 1]
        except IndexError:
            next_item = cycle[0]
        weight = gr.edge_weight((item, next_item))
        gr.set_edge_label((item, next_item), "%s %s (%s)" % (CYCLE_LABEL, number_cycle, weight))
        cycle_color = '#%s' % ((number_cycle * int('369369', 16) + int(CYCLE_COLOR_SEED, 16)) % int('ffffff', 16))
        gr.add_edge_attribute((item, next_item), ("color", cycle_color))
        gr_copy.del_edge((item, next_item))
        i += 1


def print_graph(gr, name):
    dot = write(gr)
    gvv = gv.readstring(dot)
    gv.layout(gvv, 'dot')
    format = name.split('.')[-1]
    gv.render(gvv, format, name)
