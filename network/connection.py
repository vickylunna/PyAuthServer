from .packet import Packet, PacketCollection
from .handler_interfaces import get_handler
from .descriptors import StaticValue
from .replicables import Replicable, WorldInfo
from .signals import ReplicableUnregisteredSignal, ReplicableRegisteredSignal, SignalListener
from .enums import Roles, Protocols
from .channel import ClientChannel, ServerChannel


class Connection(SignalListener):

    channel_class = None

    def __init__(self, netmode):
        self.netmode = netmode
        self.replicable = None

        self.channels = {}

        self.string_packer = get_handler(StaticValue(str))
        self.int_packer = get_handler(StaticValue(int))
        self.replicable_packer = get_handler(StaticValue(Replicable))

        self.register_signals()

    @ReplicableUnregisteredSignal.global_listener
    def notify_unregistration(self, target):
        self.channels.pop(target.instance_id)

    @ReplicableRegisteredSignal.global_listener
    def notify_registration(self, target):
        '''Create channel for context with network id
        @param instance_id: network id of context'''
        self.channels[target.instance_id] = self.channel_class(self, target)

    def on_delete(self):
        self.replicable.request_unregistration()

    def is_owner(self, replicable):
        '''Determines if a connection owns this replicable
        Searches for Replicable with same network id as our Controller'''
        # Determine if parent is our controller
        parent = replicable.uppermost
        try:
            return parent.instance_id == \
                self.replicable.instance_id

        except AttributeError:
            return False

    @staticmethod
    def get_replication_priority(entry):
        return entry[0].replication_priority

    @property
    def relevant_replicables(self, Replicable=Replicable):
        check_is_owner = self.is_owner
        channels = self.channels
        no_role = Roles.none

        for replicable in Replicable:
            # Check if remote role is permitted
            if replicable.roles.remote == no_role:
                continue

            channel = channels[replicable.instance_id]

            # Now check if we are an owner, or relevant
            is_owner = check_is_owner(replicable)
            yield (replicable, is_owner and replicable.relevant_to_owner,
                   channel)

    @property
    def prioritised_replicables(self):
        return iter(sorted(self.relevant_replicables, reverse=True,
                      key=self.get_replication_priority))

    def get_method_replication(self, replicables, collection, bandwidth):
        method_invoke = Protocols.method_invoke
        make_packet = Packet
        store_packet = collection.members.append

        for item in replicables:
            replicable, is_owner, channel = item 

            # Send RPC calls if we are the owner
            if is_owner and channel.has_rpc_calls:
                packed_id = channel.packed_id

                for rpc_call, reliable in channel.take_rpc_calls():
                    rpc_data = packed_id + rpc_call

                    store_packet(
                            make_packet(protocol=method_invoke,
                                      payload=rpc_data,
                                      reliable=reliable)
                                )
            yield item


class ClientConnection(Connection):

    channel_class = ClientChannel

    def set_replication(self, packet):
        '''Replication function
        Accepts replication packets and responds to protocol
        @param packet: replication packet'''

        instance_id = self.replicable_packer.unpack_id(packet.payload)

        # If an update for a replicable
        if packet.protocol == Protocols.replication_update:
            try:
                channel = self.channels[instance_id]

            except KeyError:
                print("Unable to find network object with id {}"
                      .format(instance_id))

            else:
                channel.set_attributes(packet.payload[
                                      self.replicable_packer.size():])

        # If it is an RPC call
        elif packet.protocol == Protocols.method_invoke:
            try:
                channel = self.channels[instance_id]

            except KeyError:
                print("Unable to find network object with id {}"
                      .format(instance_id))

            else:
                if self.is_owner(channel.replicable):
                    channel.invoke_rpc_call(packet.payload[
                                           self.replicable_packer.size():])

        # If construction for replicable
        elif packet.protocol == Protocols.replication_init:

            id_size = self.replicable_packer.size()

            type_name = self.string_packer.unpack_from(
                       packet.payload[id_size:])

            type_size = self.string_packer.size(
                        packet.payload[id_size:])

            is_connection_host = bool(self.int_packer.unpack_from(
                       packet.payload[id_size + type_size:]))

            # Create replicable of same type
            replicable_cls = Replicable.from_type_name(type_name)
            replicable = Replicable.create_or_return(replicable_cls,
                                          instance_id, register=True)
            # Perform incomplete role switch
            (replicable.roles.local,
             replicable.roles.remote) = (replicable.roles.remote,
                                         replicable.roles.local)
            # If replicable is parent (top owner)
            if is_connection_host:

                # Register as own replicable
                self.replicable = replicable

        # If it is the deletion request
        elif packet.protocol == Protocols.replication_del:

            # If the replicable exists
            try:
                replicable = Replicable.get_from_graph(instance_id)

            except LookupError:
                pass

            else:
                replicable.request_unregistration()

    def send(self, network_tick, available_bandwidth):
        '''Client connection send method
        Sends data using initialised context
        Sends RPC information
        Generator'''
        collection = PacketCollection()
        replicables = self.get_method_replication(self.prioritised_replicables,
                                                  collection,
                                                  available_bandwidth)

        # Consume iterable
        for item in replicables:
            pass

        return collection

    def receive(self, packets):
        '''Client connection receive method
        Receive data using initialised context
        Receive RPC and replication information
        Catches network errors'''
        for packet in packets:
            protocol = packet.protocol

            if protocol in Protocols:
                self.set_replication(packet)


class ServerConnection(Connection):

    channel_class = ServerChannel

    def __init__(self, netmode):
        super().__init__(netmode)

        self.cached_packets = set()

    def on_delete(self):
        '''Callback for connection deletion
        Called by ConnectionStatus when deleted'''
        super().on_delete()

        # If we own a controller destroy it
        if self.replicable:
            # We must be connected to have a controller
            print("{} disconnected!".format(self.replicable))
            self.replicable.request_unregistration()

    @ReplicableUnregisteredSignal.global_listener
    def notify_unregistration(self, target):
        '''Called when replicable dies
        @param replicable: replicable that died'''
        # Send delete packet
        channel = self.channels[target.instance_id]
        self.cached_packets.add(Packet(protocol=Protocols.replication_del,
                                    payload=channel.packed_id, reliable=True))

        super().notify_unregistration(target)

    @staticmethod
    def get_replication_priority(entry, WorldInfo=WorldInfo):
        replicable, is_owner, channel = entry
        interval = (WorldInfo.elapsed - channel.last_replication_time)
        elapsed_fraction = (interval / replicable.replication_update_period)
        return replicable.replication_priority + (elapsed_fraction - 1)

    def get_attribute_replication(self, replicables, collection, bandwidth):
        '''Yields replication packets for relevant replicable
        @param replicable: replicable to replicate'''

        make_packet = Packet
        store_packet = collection.members.append
        insert_packet = collection.members.insert

        replication_init = Protocols.replication_init
        replication_update = Protocols.replication_update

        timestamp = WorldInfo.elapsed
        is_relevant = WorldInfo.rules.is_relevant
        replicator = self.replicable

        used_bandwidth = 0
        free_bandwidth = bandwidth > 0

        for item in replicables:

            if free_bandwidth:
                replicable, is_owner, channel = item
                # Get network ID
                packed_id = channel.packed_id

                # Check whether enough time has elapsed
                interval = (timestamp - channel.last_replication_time)

                # Only send attributes if relevant
                if (interval < replicable.replication_update_period or
                    not (is_owner or is_relevant(replicator, replicable))):
                    continue

                # If we've never replicated to this channel
                if channel.is_initial:
                    # Pack the class name
                    packed_class = self.string_packer.pack(
                                   replicable.__class__.type_name)
                    packed_is_host = self.int_packer.pack(
                                  replicable == self.replicable)
                    # Send the protocol, class name and owner status to client
                    packet = make_packet(protocol=replication_init,
                                  payload=packed_id + packed_class +\
                                  packed_is_host, reliable=True)
                    # Insert the packet at the front (to ensure attribute
                    # references are valid to newly created replicables
                    insert_packet(0, packet)
                    used_bandwidth += packet.size

                # Send changed attributes
                attributes = channel.get_attributes(is_owner, timestamp)

                # If they have changed
                if attributes:
                    # This ensures references exist
                    # By calling it after all creation packets are yielded
                    update_payload = packed_id + attributes
                    packet = make_packet(
                                        protocol=replication_update,
                                        payload=update_payload,
                                        reliable=True)

                    store_packet(packet)
                    used_bandwidth += packet.size

            yield item

    def receive(self, packets):
        '''Server connection receive method
        Receive data using initialised context
        Receive RPC information'''
        # Local space variables
        is_owner = self.is_owner
        channels = self.channels

        unpacker = self.replicable_packer.unpack_id
        id_size = self.replicable_packer.size()

        method_invoke = Protocols.method_invoke

        # Run RPC invoke for each packet
        for packet in packets:

            # If it is an RPC packet
            if packet.protocol == method_invoke:
                # Unpack data
                instance_id = unpacker(packet.payload)
                channel = channels[instance_id]

                # If we have permission to execute
                if is_owner(channel.replicable):
                    channel.invoke_rpc_call(packet.payload[id_size:])

    def send(self, network_tick, available_bandwidth):
        '''Server connection send method
        Sends data using initialised context
        Sends RPC and replication information
        Generator
        @param network_tick: send any non urgent data (& RPC)
        @param available_bandwidth: number of bytes predicted available'''

        collection = PacketCollection()
        replicables = self.get_method_replication(self.prioritised_replicables,
                                                  collection,
                                                  available_bandwidth)

        available_bandwidth = max(0, available_bandwidth - collection.size)
        if network_tick:
            replicables = self.get_attribute_replication(replicables,
                                                         collection,
                                                         available_bandwidth)

        # Consume iterable
        for item in replicables:
            pass

        return collection
