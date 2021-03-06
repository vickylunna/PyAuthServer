from collections import defaultdict
from inspect import signature

from ..decorators import signal_listener
from ..metaclasses.register import TypeRegister


__all__ = ['Signal', 'ReplicableRegisteredSignal', 'ReplicableUnregisteredSignal', 'ConnectionErrorSignal',
           'ConnectionSuccessSignal', 'SignalValue',  'DisconnectSignal', 'ConnectionDeletedSignal',
           'LatencyUpdatedSignal', 'ConnectionTimeoutSignal']


class Signal(metaclass=TypeRegister):
    """Observer class for signal-like invocation"""
    subclasses = {}

    @classmethod
    def register_subtype(cls):
        cls.subscribers = {}
        cls.isolated_subscribers = {}

        cls.to_subscribe_global = {}
        cls.to_subscribe_context = {}

        cls.to_unsubscribe_context = []
        cls.to_unsubscribe_global = []

        cls.children = {}
        cls.to_remove_child = set()
        cls.to_add_child = defaultdict(set)

    @staticmethod
    def get_signals(decorated):
        return decorated.__annotations__['signals']

    @classmethod
    def register_type(cls):
        cls.register_subtype()
        cls.highest_signal = cls

    @classmethod
    def unsubscribe(cls, identifier, callback):
        """Unsubscribe from this Signal class

        :param identifier: identifier used to subscribe
        :param callback: callback that was used to subscribe
        """
        signals_data = cls.get_signals(callback)

        for signal_cls, is_context in signals_data:
            remove_list = (signal_cls.to_unsubscribe_global if is_context else signal_cls.to_unsubscribe_context)
            remove_list.append(identifier)

            signal_children = signal_cls.children

            if identifier in signal_children:
                for child in signal_children[identifier]:
                    signal_cls.remove_parent(child, identifier)

            for parent, next_children in signal_children.items():
                if identifier in next_children:
                    signal_cls.remove_parent(identifier, parent)

    @classmethod
    def set_parent(cls, identifier, parent_identifier):
        cls.to_add_child[parent_identifier].add(identifier)

    @classmethod
    def remove_parent(cls, identifier, parent_identifier):
        cls.to_remove_child.add((identifier, parent_identifier))

    @classmethod
    def on_subscribed(cls, is_contextual, subscriber, data):
        pass

    @classmethod
    def get_total_subscribers(cls):
        return len(cls.subscribers) + len(cls.isolated_subscribers)

    @classmethod
    def subscribe(cls, identifier, callback):
        """Subscribe to this Signal class using an identifier handle and a callback when invoked

        :param identifier: identifier for recipient of signal
        :param callback: callable to run when signal is invoked
        """
        signals_data = cls.get_signals(callback)
        func_signature = signature(callback)

        accepts_signal = "signal" in func_signature.parameters
        accepts_target = "target" in func_signature.parameters

        for signal_cls, is_context in signals_data:
            data_dict = (signal_cls.to_subscribe_context if is_context else signal_cls.to_subscribe_global)
            data_dict[identifier] = callback, accepts_signal, accepts_target

    @classmethod
    def update_state(cls):
        """Update subscribers and children of this Signal class"""
        # Global subscribers
        to_subscribe_global = cls.to_subscribe_global
        if to_subscribe_global:
            popitem = to_subscribe_global.popitem
            subscribers = cls.subscribers
            callback = cls.on_subscribed

            while to_subscribe_global:
                identifier, data = popitem()
                subscribers[identifier] = data
                callback(False, identifier, data)

        # Context subscribers
        to_subscribe_context = cls.to_subscribe_context
        if to_subscribe_context:
            popitem = to_subscribe_context.popitem
            subscribers = cls.isolated_subscribers
            callback = cls.on_subscribed
            while to_subscribe_context:
                identifier, data = popitem()
                subscribers[identifier] = data
                callback(True, identifier, data)

        # Remove old subscribers
        if cls.to_unsubscribe_context:
            for key in cls.to_unsubscribe_context:
                cls.subscribers.pop(key, None)
            cls.to_unsubscribe_context.clear()

        if cls.to_unsubscribe_global:
            for key in cls.to_unsubscribe_global:
                cls.isolated_subscribers.pop(key, None)
            cls.to_unsubscribe_global.clear()

        # Add new children
        if cls.to_add_child:
            cls.children.update(cls.to_add_child)
            cls.to_add_child.clear()

        # Remove old children
        if cls.to_remove_child:
            children = cls.children

            for (child, parent) in cls.to_remove_child:
                parent_children_dict = children[parent]
                # Remove from parent's children
                parent_children_dict.remove(child)
                # If we are the last child, remove parent
                if not parent_children_dict:
                    children.pop(parent)

            cls.to_remove_child.clear()

    @classmethod
    def update_graph(cls):
        """Update subscribers and children of this Signal class and any subclasses thereof"""
        for subclass in cls.subclasses.values():
            subclass.update_state()

        cls.update_state()

    @classmethod
    def invoke_signal(cls, signal_cls, target, args, kwargs, callback, supply_signal, supply_target):
        signal_args = {}

        if supply_signal:
            signal_args['signal'] = signal_cls

        if supply_target:
            signal_args['target'] = target

        signal_args.update(kwargs)
        callback(*args, **signal_args)

    @classmethod
    def invoke_targets(cls, target_dict, signal_cls, target, args, kwargs, addressee=None):
        """Invoke signals for targeted recipient.

        If recipient has children, invoke them as well.

        Children do not require parents to listen for the signal.

        :param target_dict: mapping from listener to listener information
        :param target: target referred to by Signal invocation
        :param addressee: Recipient of Signal invocation (parent of child
        tree by default)
        :param *args: tuple of additional arguments
        :param **kwargs: dict of additional keyword arguments
        """
        if addressee is None:
            addressee = target

        # If the child is a context listener
        if addressee in target_dict:
            callback, supply_signal, supply_target = target_dict[addressee]
            # Invoke with the same target context even if this is a child
            cls.invoke_signal(signal_cls, target, args, kwargs, callback, supply_signal, supply_target)

        # Update children of this listener
        if addressee in cls.children:
            for target_child in cls.children[addressee]:
                cls.invoke_targets(target_dict, signal_cls, target, args, kwargs, addressee=target_child)

    @classmethod
    def invoke_general(cls, subscriber_dict, signal_cls, target, args, kwargs):
        """Invoke signals for non targeted listeners

        :param subscriber_dict: mapping from listener to listener information
        :param target: target referred to by Signal invocation
        :param *args: tuple of additional arguments
        :param **kwargs: dict of additional keyword arguments
        """
        for (callback, supply_signal, supply_target) in subscriber_dict.values():
            cls.invoke_signal(signal_cls, target, args, kwargs, callback, supply_signal, supply_target)

    @classmethod
    def invoke(cls, *args, signal_cls=None, target=None, **kwargs):
        """Invoke signals for a Signal type

        :param target: target referred to by Signal invocation
        :param *args: tuple of additional arguments
        :param **kwargs: dict of additional keyword arguments
        """
        if signal_cls is None:
            signal_cls = cls

        if target:
            cls.invoke_targets(cls.isolated_subscribers, signal_cls, target, args, kwargs)
        cls.invoke_general(cls.subscribers, signal_cls, target, args, kwargs)
        cls.invoke_parent(signal_cls, target, args, kwargs)

    @classmethod
    def invoke_parent(cls, signal_cls, target, args, kwargs):
        """Invoke signals for superclass of Signal type

        :param target: target referred to by Signal invocation
        :param *args: tuple of additional arguments
        :param **kwargs: dict of additional keyword arguments
        """
        if cls.highest_signal == cls:
            return

        try:
            parent = cls.__mro__[1]

        except IndexError:
            return

        parent.invoke(*args, signal_cls=signal_cls, target=target, **kwargs)

    @classmethod
    def global_listener(cls, func):
        """Decorator for global signal listeners

        :param func: function to decorate
        :returns: passed function func
        """
        return signal_listener(cls, True)(func)

    @classmethod
    def listener(cls, func):
        """Decorator for targeted signal listeners

        :param func: function to decorate
        :returns: passed function func
        """
        return signal_listener(cls, False)(func)


class CachedSignal(Signal):

    @classmethod
    def register_subtype(cls):
        # Unfortunate hack to reproduce super() behaviour
        Signal.register_subtype.__func__(cls)
        cls.cache = []

    @classmethod
    def invoke(cls, *args, subscriber_data=None, signal_cls=None, target=None, **kwargs):
        if signal_cls is None:
            signal_cls = cls

        # Don't cache from cache itself!
        if subscriber_data is None:
            cls.cache.append((signal_cls, target, args, kwargs))
            cls.invoke_targets(cls.isolated_subscribers, signal_cls, target, args, kwargs)
            cls.invoke_general(cls.subscribers, signal_cls, target, args, kwargs)

        else:
            # Otherwise run a general invocation on new subscriber
            cls.invoke_general(subscriber_data, signal_cls, target, args, kwargs)

        cls.invoke_parent(signal_cls, target, args, kwargs)

    @classmethod
    def on_subscribed(cls, is_contextual, subscriber, data):
        # Only inform global listeners (wouldn't work anyway)
        if is_contextual:
            return

        subscriber_info = {subscriber: data}
        invoke_signal = cls.invoke
        for signal_cls, target, args, kwargs in cls.cache:
            invoke_signal(*args, signal_cls=signal_cls, target=target, subscriber_data=subscriber_info, **kwargs)


class SignalValue:
    """Container for signal callback return arguments"""

    __slots__ = '_value', '_changed', '_single_value'

    def __init__(self, default=None, single_value=False):
        self._single_value = single_value
        self._value = default
        self._changed = False

    @property
    def changed(self):
        return self._changed

    @property
    def value(self):
        return self._value

    @value.setter
    def value(self, value):
        if self._single_value and self._changed:
            raise ValueError("Value already set")

        self._value = value
        self._changed = True

    def create_getter(self):
        """Create a getter function for the internal value"""
        def wrapper():
            return self.value

        return wrapper

    def create_setter(self, value):
        """Create a setter function for the internal value

        :param value: value to set when invoked
        """
        def wrapper():
            self.value = value

        return wrapper


class ReplicableRegisteredSignal(CachedSignal):
    pass


class ReplicableUnregisteredSignal(Signal):
    pass


class DisconnectSignal(Signal):
    pass


class ConnectionTimeoutSignal(Signal):
    pass


class ConnectionErrorSignal(Signal):
    pass


class ConnectionSuccessSignal(Signal):
    pass


class ConnectionDeletedSignal(Signal):
    pass


class LatencyUpdatedSignal(Signal):
    pass