# Copyright (c) 2015 VMware, Inc. All rights reserved.
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
from congress.datalog.base import ACTION_POLICY_TYPE
from congress.datalog.base import NONRECURSIVE_POLICY_TYPE
from congress.datalog import compile
from congress.datalog.compile import Event
from congress.datalog.ruleset import RuleSet
from congress.datalog.topdown import TopDownTheory
from congress.datalog.utility import iterstr
from congress.exception import PolicyException
from congress.openstack.common import log as logging

LOG = logging.getLogger(__name__)


class NonrecursiveRuleTheory(TopDownTheory):
    """A non-recursive collection of Rules."""

    def __init__(self, name=None, abbr=None,
                 schema=None, theories=None):
        super(NonrecursiveRuleTheory, self).__init__(
            name=name, abbr=abbr, theories=theories, schema=schema)
        # dictionary from table name to list of rules with that table in head
        self.rules = RuleSet()
        self.kind = NONRECURSIVE_POLICY_TYPE

    # External Interface

    # SELECT implemented by TopDownTheory

    def initialize_tables(self, tablenames, facts):
        """Event handler for (re)initializing a collection of tables

        @facts must be an iterable containing compile.Fact objects.
        """
        LOG.info("initialize_tables")
        cleared_tables = set(tablenames)
        for t in tablenames:
            self.rules.clear_table(t)

        count = 0
        for f in facts:
            if f.table not in cleared_tables:
                self.rules.clear_table(f.table)
                cleared_tables.add(f.table)
            self.rules.add_rule(f.table, f)
            count += 1

        LOG.info("initialized %d tables with %d facts",
                 len(cleared_tables), count)

    def insert(self, rule):
        changes = self.update([Event(formula=rule, insert=True)])
        return [event.formula for event in changes]

    def delete(self, rule):
        changes = self.update([Event(formula=rule, insert=False)])
        return [event.formula for event in changes]

    def update(self, events):
        """Apply EVENTS.

           And return the list of EVENTS that actually
           changed the theory.  Each event is the insert or delete of
           a policy statement.
           """
        changes = []
        self.log(None, "Update %s", iterstr(events))
        try:
            for event in events:
                formula = compile.reorder_for_safety(event.formula)
                if event.insert:
                    if self._insert_actual(formula):
                        changes.append(event)
                else:
                    if self._delete_actual(formula):
                        changes.append(event)
        except Exception as e:
            LOG.exception("runtime caught an exception")
            raise e

        return changes

    def update_would_cause_errors(self, events):
        """Return a list of PolicyException.

        Return a list of PolicyException if we were
        to apply the insert/deletes of policy statements dictated by
        EVENTS to the current policy.
        """
        self.log(None, "update_would_cause_errors %s", iterstr(events))
        errors = []
        for event in events:
            if not compile.is_datalog(event.formula):
                errors.append(PolicyException(
                    "Non-formula found: {}".format(
                        str(event.formula))))
            else:
                if event.formula.is_atom():
                    errors.extend(compile.fact_errors(
                        event.formula, self.theories, self.name))
                else:
                    errors.extend(compile.rule_errors(
                        event.formula, self.theories, self.name))
        # Would also check that rules are non-recursive, but that
        #   is currently being handled by Runtime.  The current implementation
        #   disallows recursion in all theories.
        return errors

    def define(self, rules):
        """Empties and then inserts RULES."""
        self.empty()
        return self.update([Event(formula=rule, insert=True)
                            for rule in rules])

    def empty(self, tablenames=None, invert=False):
        """Deletes contents of theory.

        If provided, TABLENAMES causes only the removal of all rules
        that help define one of the tables in TABLENAMES.
        If INVERT is true, all rules defining anything other than a
        table in TABLENAMES is deleted.
        """
        if tablenames is None:
            self.rules.clear()
            return
        if invert:
            to_clear = set(self.defined_tablenames()) - set(tablenames)
        else:
            to_clear = tablenames
        for table in to_clear:
            self.rules.clear_table(table)

    def policy(self):
        # eliminate all rules with empty bodies
        return [p for p in self.content() if len(p.body) > 0]

    def get_arity_self(self, tablename, theory):
        if tablename not in self.rules:
            return None
        rules = self.rules.get_rules(tablename)
        if len(rules) == 0:
            return None
        try:
            rule = next(rule for rule in rules if rule.head.theory == theory)
        except StopIteration:
            return None
        return len(rule.head.arguments)

    def __contains__(self, formula):
        if compile.is_atom(formula):
            return self.rules.contains(formula.table, formula)
        else:
            return self.rules.contains(formula.head.table, formula)

    # Internal Interface

    def _insert_actual(self, rule):
        """Insert RULE and return True if there was a change."""
        if compile.is_atom(rule):
            rule = compile.Rule(rule, [], rule.location)
        self.log(rule.head.table, "Insert: %s", repr(rule))
        return self.rules.add_rule(rule.head.table, rule)

    def _delete_actual(self, rule):
        """Delete RULE and return True if there was a change."""
        if compile.is_atom(rule):
            rule = compile.Rule(rule, [], rule.location)
        self.log(rule.head.table, "Delete: %s", rule)
        return self.rules.discard_rule(rule.head.table, rule)

    def content(self, tablenames=None):
        if tablenames is None:
            tablenames = self.rules.keys()
        results = []
        for table in tablenames:
            if table in self.rules:
                results.extend(self.rules.get_rules(table))
        return results

    def head_index(self, table, match_literal=None):
        """Return head index.

        This routine must return all the formulas pertinent for
        top-down evaluation when a literal with TABLE is at the top
        of the stack.
        """
        if table in self.rules:
            return self.rules.get_rules(table, match_literal)
        return []

    def arity(self, tablename):
        """Return the number of arguments TABLENAME takes.

        None if unknown because TABLENAME is not defined here.
        """
        # assuming a fixed arity for all tables
        formulas = self.head_index(tablename)
        if len(formulas) == 0:
            return None
        first = formulas[0]
        # should probably have an overridable function for computing
        #   the arguments of a head.  Instead we assume heads have .arguments
        return len(self.head(first).arguments)

    def defined_tablenames(self):
        """Returns list of table names defined in/written to this theory."""
        return self.rules.keys()

    def head(self, formula):
        """Given the output from head_index(), return the formula head.

        Given a FORMULA, return the thing to unify against.
        Usually, FORMULA is a compile.Rule, but it could be anything
        returned by HEAD_INDEX.
        """
        return formula.head

    def body(self, formula):
        """Return formula body.

        Given a FORMULA, return a list of things to push onto the
        top-down eval stack.
        """
        return formula.body


class ActionTheory(NonrecursiveRuleTheory):
    """ActionTheory object.

    Same as NonrecursiveRuleTheory except it has fewer constraints
    on the permitted rules. Still working out the details.
    """
    def __init__(self, name=None, abbr=None,
                 schema=None, theories=None):
        super(ActionTheory, self).__init__(name=name, abbr=abbr,
                                           schema=schema, theories=theories)
        self.kind = ACTION_POLICY_TYPE

    def update_would_cause_errors(self, events):
        """Return a list of PolicyException.

        Return a list of PolicyException if we were
        to apply the events EVENTS to the current policy.
        """
        self.log(None, "update_would_cause_errors %s", iterstr(events))
        errors = []
        for event in events:
            if not compile.is_datalog(event.formula):
                errors.append(PolicyException(
                    "Non-formula found: {}".format(
                        str(event.formula))))
            else:
                if event.formula.is_atom():
                    errors.extend(compile.fact_errors(
                        event.formula, self.theories, self.name))
                else:
                    errors.extend(compile.rule_head_has_no_theory(
                        event.formula,
                        permit_head=lambda lit: lit.is_update()))
                    # Should put this back in place, but there are some
                    # exceptions that we don't handle right now.
                    # Would like to mark some tables as only being defined
                    #   for certain bound/free arguments and take that into
                    #   account when doing error checking.
                    # errors.extend(compile.rule_negation_safety(event.formula))
        return errors


class UnsafeNonrecursiveRuleTheory(NonrecursiveRuleTheory):
    """Nonrecursive rule theory without any safety checks."""
    def update_would_cause_errors(self, events):
        return []
