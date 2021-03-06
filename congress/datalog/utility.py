# Copyright (c) 2013 VMware, Inc. All rights reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
#

import collections


class Graph(object):
    """A standard graph data structure.

    With routines applicable to analysis of policy.
    """
    class dfs_data(object):
        """Data for each node in graph during depth-first-search."""
        def __init__(self, begin=None, end=None):
            self.begin = begin
            self.end = end

    class edge_data(object):
        """Data for each edge in graph."""
        def __init__(self, node=None, label=None):
            self.node = node
            self.label = label

        def __str__(self):
            return "<Label:%s, Node:%s>" % (self.label, self.node)

        def __eq__(self, other):
            return self.node == other.node and self.label == other.label

        def __hash__(self):
            return hash(str(self))

    def __init__(self, graph=None):
        self.edges = {}   # dict from node to list of nodes
        self.nodes = {}   # dict from node to info about node
        self.cycles = None

    def __or__(self, other):
        # do this the simple way so that subclasses get this code for free
        g = self.__class__()
        for node in self.nodes:
            g.add_node(node)
        for node in other.nodes:
            g.add_node(node)

        for name in self.edges:
            for edge in self.edges[name]:
                g.add_edge(name, edge.node, label=edge.label)
        for name in other.edges:
            for edge in other.edges[name]:
                g.add_edge(name, edge.node, label=edge.label)
        return g

    def __ior__(self, other):
        if len(other) == 0:
            # no changes if other is empty
            return self
        self.cycles = None
        for name in other.nodes:
            self.add_node(name)
        for name in other.edges:
            for edge in other.edges[name]:
                self.add_edge(name, edge.node, label=edge.label)
        return self

    def __len__(self):
        return (len(self.nodes) +
                reduce(lambda x, y: x+y,
                       (len(x) for x in self.edges.values()),
                       0))

    def add_node(self, val):
        """Add node VAL to graph."""
        if val not in self.nodes:  # preserve old node info
            self.nodes[val] = None
            return True
        return False

    def delete_node(self, val):
        """Delete node VAL from graph and all edges."""
        try:
            del self.nodes[val]
            del self.edges[val]
        except KeyError:
            assert val not in self.edges

    def add_edge(self, val1, val2, label=None):
        """Add edge from VAL1 to VAL2 with label LABEL to graph.

        Also adds the nodes.
        """
        self.cycles = None  # so that has_cycles knows it needs to rerun
        self.add_node(val1)
        self.add_node(val2)
        val = self.edge_data(node=val2, label=label)
        try:
            self.edges[val1].add(val)
        except KeyError:
            self.edges[val1] = set([val])

    def delete_edge(self, val1, val2, label=None):
        """Delete edge from VAL1 to VAL2 with label LABEL.

        LABEL must match (even if None).  Does not delete nodes.
        """
        try:
            edge = self.edge_data(node=val2, label=label)
            self.edges[val1].remove(edge)
        except KeyError:
            # KeyError either because val1 or edge
            return
        self.cycles = None

    def node_in(self, val):
        return val in self.nodes

    def edge_in(self, val1, val2, label=None):
        return (val1 in self.edges and
                self.edge_data(val2, label) in self.edges[val1])

    def depth_first_search(self):
        """Run depth first search on the graph.

        Also modify self.nodes, self.counter, and self.cycle.
        """
        self.reset()
        for node in self.nodes:
            if self.nodes[node].begin is None:
                self.dfs(node)

    def depth_first_search_node(self, node):
        """Run depth-first search on the nodes reachable from NODE.

        Modifies self.nodes, self.counter, and self.cycle.
        """
        self.reset()
        self.dfs(node)

    def reset(self):
        """Return nodes to pristine state."""
        for node in self.nodes:
            self.nodes[node] = self.dfs_data()
        self.counter = 0
        self.cycles = []
        self.backpath = {}

    def dfs(self, node):
        """DFS implementation.

        Assumes data structures have been properly prepared.
        Creates start/begin times on nodes and adds to self.cycles.
        """
        self.nodes[node].begin = self.next_counter()
        if node in self.edges:
            for edge in self.edges[node]:
                self.backpath[edge.node] = node
                if self.nodes[edge.node].begin is None:
                    self.dfs(edge.node)
                elif self.nodes[edge.node].end is None:
                    cycle = self.construct_cycle(edge.node, self.backpath)
                    self.cycles.append(cycle)
        self.nodes[node].end = self.next_counter()

    def construct_cycle(self, node, history):
        """Construct a cycle.

        Construct a cycle ending at node NODE after having traversed
        the nodes in the list HISTORY.
        """
        prev = history[node]
        sofar = [prev]
        while prev != node:
            prev = history[prev]
            sofar.append(prev)
        sofar.append(node)
        sofar.reverse()
        return sofar

    def stratification(self, labels):
        """Return the stratification result.

        Return mapping of node name to integer indicating the
        stratum to which that node is assigned. LABELS is the list
        of edge labels that dictate a change in strata.
        """
        stratum = {}
        for node in self.nodes:
            stratum[node] = 1
        changes = True
        while changes:
            changes = False
            for node in self.edges:
                for edge in self.edges[node]:
                    oldp = stratum[node]
                    if edge.label in labels:
                        stratum[node] = max(stratum[node],
                                            1 + stratum[edge.node])
                    else:
                        stratum[node] = max(stratum[node],
                                            stratum[edge.node])
                    if oldp != stratum[node]:
                        changes = True
                    if stratum[node] > len(self.nodes):
                        return None
        return stratum

    def roots(self):
        """Return list of nodes with no incoming edges."""
        possible_roots = set(self.nodes)
        for node in self.edges:
            for edge in self.edges[node]:
                if edge.node in possible_roots:
                    possible_roots.remove(edge.node)
        return possible_roots

    def has_cycle(self):
        """Checks if there are cycles.

        Run depth_first_search only if it has not already been run.
        """
        self.depth_first_search()
        return len(self.cycles) > 0

    def dependencies(self, node):
        """Returns collection of node names reachable from NODE.

        If NODE does not exist in graph, returns None.
        """
        if node not in self.nodes:
            return None
        self.reset()
        node_obj = self.nodes[node]

        if node_obj is None or node_obj.begin is None or node_obj.end is None:
            self.depth_first_search_node(node)
            node_obj = self.nodes[node]
        begin = node_obj.begin
        end = node_obj.end
        return set([n for n, dfs_obj in self.nodes.iteritems()
                    if begin <= dfs_obj.begin and dfs_obj.end <= end])

    def next_counter(self):
        """Return next counter value and increment the counter."""
        self.counter += 1
        return self.counter - 1

    def __str__(self):
        s = "{"
        for node in self.nodes:
            s += "(" + str(node) + " : ["
            if node in self.edges:
                s += ", ".join([str(x) for x in self.edges[node]])
            s += "],\n"
        s += "}"
        return s


class BagGraph(Graph):
    """A graph data structure with bag semantics for nodes and edges.

    Keeps track of the number of times each node/edge has been inserted.
    A node/edge is removed from the graph only once it has been deleted
    the same number of times it was inserted.  Deletions when no node/edge
    already exist are ignored.
    """
    def __init__(self, graph=None):
        super(BagGraph, self).__init__(graph)
        self._node_refcounts = {}  # dict from node to counter
        self._edge_refcounts = {}  # dict from edge to counter

    def add_node(self, val):
        """Add node VAL to graph."""
        super(BagGraph, self).add_node(val)
        if val in self._node_refcounts:
            self._node_refcounts[val] += 1
        else:
            self._node_refcounts[val] = 1

    def delete_node(self, val):
        """Delete node VAL from graph (but leave all edges)."""
        if val not in self._node_refcounts:
            return
        self._node_refcounts[val] -= 1
        if self._node_refcounts[val] == 0:
            super(BagGraph, self).delete_node(val)
            del self._node_refcounts[val]

    def add_edge(self, val1, val2, label=None):
        """Add edge from VAL1 to VAL2 with label LABEL to graph.

        Also adds the nodes VAL1 and VAL2 (important for refcounting).
        """
        super(BagGraph, self).add_edge(val1, val2, label=label)
        edge = (val1, val2, label)
        if edge in self._edge_refcounts:
            self._edge_refcounts[edge] += 1
        else:
            self._edge_refcounts[edge] = 1

    def delete_edge(self, val1, val2, label=None):
        """Delete edge from VAL1 to VAL2 with label LABEL.

        LABEL must match (even if None).  Also deletes nodes
        whenever the edge exists.
        """
        edge = (val1, val2, label)
        if edge not in self._edge_refcounts:
            return
        self.delete_node(val1)
        self.delete_node(val2)
        self._edge_refcounts[edge] -= 1
        if self._edge_refcounts[edge] == 0:
            super(BagGraph, self).delete_edge(val1, val2, label=label)
            del self._edge_refcounts[edge]

    def node_in(self, val):
        return val in self._node_refcounts

    def edge_in(self, val1, val2, label=None):
        return (val1, val2, label) in self._edge_refcounts

    def node_count(self, node):
        if node in self._node_refcounts:
            return self._node_refcounts[node]
        else:
            return 0

    def edge_count(self, val1, val2, label=None):
        edge = (val1, val2, label)
        if edge in self._edge_refcounts:
            return self._edge_refcounts[edge]
        else:
            return 0

    def __len__(self):
        return (reduce(lambda x, y: x+y, self._node_refcounts.values(), 0) +
                reduce(lambda x, y: x+y, self._edge_refcounts.values(), 0))

    def __str__(self):
        s = "{"
        for node in self.nodes:
            s += "(%s *%s: [" % (str(node), self._node_refcounts[node])
            if node in self.edges:
                s += ", ".join(
                    ["%s *%d" %
                        (str(x), self.edge_count(node, x.node, x.label))
                        for x in self.edges[node]])
            s += "],\n"
        s += "}"
        return s


class OrderedSet(collections.MutableSet):
    """Provide sequence capabilities with rapid membership checks.

    Mostly lifted from the activestate recipe[1] linked at Python's collections
    documentation[2]. Some modifications, such as returning True or False from
    add(key) and discard(key) if a change is made.

    [1] - http://code.activestate.com/recipes/576694/
    [2] - https://docs.python.org/2/library/collections.html
    """
    def __init__(self, iterable=None):
        self.end = end = []
        end += [None, end, end]         # sentinel node for doubly linked list
        self.map = {}                   # key --> [key, prev, next]
        if iterable is not None:
            self |= iterable

    def __len__(self):
        return len(self.map)

    def __contains__(self, key):
        return key in self.map

    def add(self, key):
        if key not in self.map:
            end = self.end
            curr = end[1]
            curr[2] = end[1] = self.map[key] = [key, curr, end]
            return True
        return False

    def discard(self, key):
        if key in self.map:
            key, prev, next = self.map.pop(key)
            prev[2] = next
            next[1] = prev
            return True
        return False

    def __iter__(self):
        end = self.end
        curr = end[2]
        while curr is not end:
            yield curr[0]
            curr = curr[2]

    def __reversed__(self):
        end = self.end
        curr = end[1]
        while curr is not end:
            yield curr[0]
            curr = curr[1]

    def pop(self, last=True):
        if not self:
            raise KeyError('pop from an empty set')
        key = self.end[1][0] if last else self.end[2][0]
        self.discard(key)
        return key

    def __repr__(self):
        if not self:
            return '%s()' % (self.__class__.__name__,)
        return '%s(%r)' % (self.__class__.__name__, list(self))

    def __eq__(self, other):
        if isinstance(other, OrderedSet):
            return len(self) == len(other) and list(self) == list(other)
        else:
            return False


# A silly trick to get around casting large iterables to strings unless
# necessary. This ought to be eliminated when possible by paring down
# what's logged.
class iterstr(object):
    def __init__(self, iterable):
        self.__iterable = iterable
        self.__interpolated = None

    def __getattribute__(self, name):
        if self.__interpolated is None:
            self.__interpolated = ("[" +
                                   ";".join([str(x) for x in self.__iterable])
                                   + "]")
        return getattr(self.__interpolated, name)
