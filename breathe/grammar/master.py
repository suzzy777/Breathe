from dragonfly import (
    Grammar,
    Rule,
    Text,
    ElementBase,
    Function,
    Context,
    Alternative,
    Compound,
    DictList,
)
from ..rules import RepeatRule, SimpleRule, ContextSwitcher
from .subgrammar import SubGrammar
from ..elements import BoundCompound, ManualContext
from ..errors import CommandSkippedWarning
from six import string_types
import warnings


class Master(Grammar):

    MAX_REPETITIONS = 16

    def __init__(self, **kwargs):
        Grammar.__init__(self, "Merger", context=None, **kwargs)

        self.count = 0
        # List[Compound]
        self.core_commands = []
        # List[List[Compound]]
        self.context_commands = []
        # List[Context]
        self.contexts = []

        # Dict[Tuple[bool], SubGrammar]
        # Key of dictionary is the contexts the rule matched
        self.grammar_map = {}

        # Dict[str, ElementBase]
        self.global_extras = {}

        self.manual_context_dictlist = DictList("manual_contexts")
        self.add_rule(
            ContextSwitcher(self.manual_context_dictlist)
        )

        self.load()

    def counter(self):
        """
            Generate numbers for unique naming of rules and grammars
        """
        self.count += 1
        return str(self.count)

    def construct_extras(self, extras=None, defaults=None):
        # Global extras may be overridden
        full_extras = self.global_extras.copy()
        if extras:
            assert isinstance(extras, (list, tuple))
            if defaults is None:
                for e in extras:
                    assert isinstance(e, ElementBase)
                    full_extras.update({e.name: e})
            else:
                assert isinstance(defaults, dict)
                for e in extras:
                    assert isinstance(e, ElementBase)
                    if not e.has_default() and e.name in defaults:
                        e._default = defaults[e.name]
                    full_extras.update({e.name: e})
        return full_extras

    def construct_commands(self, mapping, extras=None):
        children = []
        assert isinstance(mapping, dict)
        for spec, value in mapping.items():
            assert isinstance(spec, string_types)
            if callable(value):
                value = Function(value)
            try:
                c = BoundCompound(spec, extras=extras, value=value)
                children.append(c)
            except Exception as e:
                # No need to raise, we can just skip this command
                # Usually due to missing extras
                warnings.warn(str(e), CommandSkippedWarning)
        return children

    def add_commands(
        self, context=None, mapping=None, extras=None, defaults=None, ccr=True
    ):
        """Add a set of commands which can be recognised continuously.

        Keyword Arguments:
            context {Context} -- Context in which these commands will be active, if None, commands will be global (default: {None})
            mapping {dict} -- Dictionary of rule specs to dragonfly Actions (default: {None})
            extras {list} -- Extras which will be available for these commands (default: {None})
            defaults {dict} -- Defaults for the extras, if necessary (default: {None})
            ccr {bool} -- Whether these commands should be recognised continuously (default: {True})
        """

        if not mapping:
            return

        full_extras = self.construct_extras(extras, defaults)
        children = self.construct_commands(mapping, full_extras)

        if not children:
            return

        if isinstance(context, ManualContext):
            if context.name in self.manual_context_dictlist:
                # Everything we want to enable with this command
                # should be referencing the same object
                # TODO: Logical versions
                context = self.manual_context_dictlist[context.name]
            else:
                self.manual_context_dictlist[context.name] = context

        if not ccr:
            rule = SimpleRule(
                element=Alternative(children),
                context=context
                )
            grammar = Grammar("NonCCR" + self.counter())
            grammar.add_rule(rule)
            grammar.load()
            return

        if context is None:
            self.core_commands.extend(children)
        else:
            assert isinstance(context, Context)
            self.context_commands.append(children)
            self.contexts.append(context)

    def add_global_extras(self, *extras):
        """
            Global extras will be available to all commands,
            but must be added before the commands which use them.

            Defaults should be assigned on the extras themselves.
        """
        if len(extras) == 1 and isinstance(extras[0], list):
            extras = extras[0]
        for e in extras:
            assert isinstance(e, ElementBase)
            self.global_extras.update({e.name: e})

    def add_repeater(self, matches):
        """
            Takes a tuple of bools, corresponding to which contexts were matched,
            and loads a SubGrammar containing a RepeatRule with all relevant commands in.
        """
        matched_commands = []
        for command_list in [l for (l, b) in zip(self.context_commands, matches) if b]:
            matched_commands.extend(command_list)
        matched_commands.extend(self.core_commands)

        if not matched_commands:
            return

        rule = RepeatRule("Repeater%s" % self.counter(), matched_commands)
        subgrammar = SubGrammar("SG%s" % self.counter())
        subgrammar.add_rule(rule)

        subgrammar.load()
        self.grammar_map[matches] = subgrammar

    def process_begin(self, executable, title, handle):
        """
            Check which of our contexts the current window matches and look this up in our grammar map.

            If we haven't seen this combination before, add a new subgrammar for it.

            Enable the subgrammar which matches the window, and disable all others.
        """
        active_contexts = tuple(
            [c.matches(executable, title, handle) for c in self.contexts]
        )

        if active_contexts not in self.grammar_map:
            self.add_repeater(active_contexts)

        for contexts, subgrammar in self.grammar_map.items():
            if active_contexts == contexts:
                subgrammar.enable()
                # print("%s active" % subgrammar.name)
                # print(subgrammar.rules[0].element._child.children)
            else:
                subgrammar.disable()

            subgrammar._process_begin()
