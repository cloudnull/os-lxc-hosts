#!/usr/bin/env python
# Copyright 2014, Rackspace US, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# (c) 2014, Kevin Carter <kevin.carter@rackspace.com>

import argparse
import datetime
import hashlib
import json
import os
import Queue
import random
import tarfile
import uuid

try:
    import yaml
except ImportError:
    print('Missing Dependency, "PyYAML"')

try:
    import netaddr
except ImportError:
    print('Missing Dependency, "netaddr"')

USED_IPS = []
INVENTORY_SKEL = {
    '_meta': {
        'hostvars': {}
    }
}

# This is a list of items that all hosts should have at all times.
# Any new item added to inventory that will used as a default argument in the
# inventory setup should be added to this list.
REQUIRED_HOSTVARS = [
    'is_metal',
    'ansible_ssh_host',
    'physical_host_group',
    'container_address',
    'container_name',
    'container_networks',
    'physical_host',
    'component'
]


def args():
    """Setup argument Parsing."""
    parser = argparse.ArgumentParser(
        usage='%(prog)s',
        description='Rackspace Openstack, Inventory Generator',
        epilog='Inventory Generator Licensed "Apache 2.0"')

    parser.add_argument(
        '--file',
        help='User defined configuration file',
        required=False,
        default=None
    )
    parser.add_argument(
        '--list',
        help='List all entries',
        action='store_true'
    )

    return vars(parser.parse_args())


def get_ip_address(name, ip_q):
    """Return an IP address from our IP Address queue."""
    try:
        ip_addr = ip_q.get(timeout=1)
        while ip_addr in USED_IPS:
            ip_addr = ip_q.get(timeout=1)
        else:
            append_if(array=USED_IPS, item=ip_addr)
            return str(ip_addr)
    except AttributeError:
        return None
    except Queue.Empty:
        raise SystemExit(
            'Cannot retrieve requested amount of IP addresses. Increase the %s'
            ' range in your rpc_user_config.yml.' % name
        )


def _load_ip_q(cidr, ip_q):
    """Load the IP queue with all IP address from a given cidr.

    :param cidr: ``str``  IP address with cidr notation
    """
    _all_ips = [str(i) for i in list(netaddr.IPNetwork(cidr))]
    base_exclude = [
        str(netaddr.IPNetwork(cidr).network),
        str(netaddr.IPNetwork(cidr).broadcast)
    ]
    USED_IPS.extend(base_exclude)
    for ip in random.sample(_all_ips, len(_all_ips)):
        if ip not in USED_IPS:
            ip_q.put(ip)


def _parse_belongs_to(key, belongs_to, inventory):
    """Parse all items in a `belongs_to` list.

    :param key: ``str``  Name of key to append to a given entry
    :param belongs_to: ``list``  List of items to iterate over
    :param inventory: ``dict``  Living dictionary of inventory
    """
    for item in belongs_to:
        if key not in inventory[item]['children']:
            append_if(array=inventory[item]['children'], item=key)


def _build_container_hosts(container_affinity, container_hosts, type_and_name,
                           inventory, host_type, container_type,
                           container_host_type, physical_host_type, config,
                           is_metal, assignment):
    """Add in all of hte host associations into inventory.

    This will add in all of the hosts into the inventory based on the given
    affinity for a container component and its subsequent type groups.

    :param container_affinity: ``int`` Set the number of a given container
    :param container_hosts: ``list`` List of containers on an host
    :param type_and_name: ``str`` Combined name of host and container name
    :param inventory: ``dict``  Living dictionary of inventory
    :param host_type: ``str``  Name of the host type
    :param container_type: ``str``  Type of container
    :param container_host_type: ``str`` Type of host
    :param physical_host_type: ``str``  Name of physical host group
    :param config: ``dict``  User defined information
    :param is_metal: ``bol``  If true, a container entry will not be built
    :param assignment: ``str`` Name of container component target
    """
    container_list = []
    for make_container in range(container_affinity):
        for i in container_hosts:
            if '%s-' % type_and_name in i:
                append_if(array=container_list, item=i)

        existing_count = len(list(set(container_list)))
        if existing_count < container_affinity:
            hostvars = inventory['_meta']['hostvars']
            container_mapping = inventory[container_type]['children']
            address = None

            if is_metal is False:
                cuuid = '%s' % uuid.uuid4()
                cuuid = cuuid.split('-')[0]
                container_host_name = '%s-%s' % (type_and_name, cuuid)
                hostvars_options = hostvars[container_host_name] = {}
                if container_host_type not in inventory:
                    inventory[container_host_type] = {
                        "hosts": [],
                    }

                append_if(
                    array=inventory[container_host_type]["hosts"],
                    item=container_host_name
                )
                append_if(array=container_hosts, item=container_host_name)
            else:
                if host_type not in hostvars:
                    hostvars[host_type] = {}

                hostvars_options = hostvars[host_type]
                container_host_name = host_type
                host_type_config = config[physical_host_type][host_type]
                address = host_type_config.get('ip')

            # Create a host types containers group and append it to inventory
            host_type_containers = '%s_containers' % host_type
            append_if(array=container_mapping, item=host_type_containers)

            hostvars_options.update({
                'is_metal': is_metal,
                'ansible_ssh_host': address,
                'container_address': address,
                'container_name': container_host_name,
                'physical_host': host_type,
                'physical_host_group': physical_host_type,
                'component': assignment
            })


def _append_container_types(inventory, host_type):
    """Append the "physical_host" type to all containers.

    :param inventory: ``dict``  Living dictionary of inventory
    :param host_type: ``str``  Name of the host type
    """
    for _host in inventory['_meta']['hostvars'].keys():
        hdata = inventory['_meta']['hostvars'][_host]
        if 'container_name' in hdata:
            if hdata['container_name'].startswith(host_type):
                if 'physical_host' not in hdata:
                    hdata['physical_host'] = host_type


def _append_to_host_groups(inventory, container_type, assignment, host_type,
                           type_and_name, host_options):
    """Append all containers to physical (logical) groups based on host types.

    :param inventory: ``dict``  Living dictionary of inventory

    :param container_type: ``str``  Type of container
    :param assignment: ``str`` Name of container component target
    :param host_type: ``str``  Name of the host type
    :param type_and_name: ``str`` Combined name of host and container name
    """
    physical_group_type = '%s_all' % container_type.split('_')[0]
    if physical_group_type not in inventory:
        inventory[physical_group_type] = {'hosts': []}

    iph = inventory[physical_group_type]['hosts']
    iah = inventory[assignment]['hosts']
    for hname, hdata in inventory['_meta']['hostvars'].iteritems():
        if 'container_types' in hdata or 'container_name' in hdata:
            if 'container_name' not in hdata:
                container = hdata['container_name'] = hname
            else:
                container = hdata['container_name']

            component = hdata.get('component')
            if container.startswith(host_type):
                if 'physical_host' not in hdata:
                    hdata['physical_host'] = host_type

                if container.startswith('%s-' % type_and_name):
                    append_if(array=iah, item=container)
                elif hdata.get('is_metal') is True:
                    if component == assignment:
                        append_if(array=iah, item=container)

                if container.startswith('%s-' % type_and_name):
                    append_if(array=iph, item=container)
                elif hdata.get('is_metal') is True:
                    if container.startswith(host_type):
                        append_if(array=iph, item=container)

                # Append any options in config to the host_vars of a container
                container_vars = host_options.get('container_vars')
                if isinstance(container_vars, dict):
                    for _keys, _vars in container_vars.items():
                        # Copy the options dictionary for manipulation
                        if isinstance(_vars, dict):
                            options = _vars.copy()
                        else:
                            options = _vars

                        limit = None
                        # If a limit is set use the limit string as a filter
                        # for the container name and see if it matches.
                        if 'limit_container_types' in options:
                            limit = options.pop(
                                'limit_container_types', None
                            )

                        if limit is None or limit in container:
                            hdata[_keys] = options


def _add_container_hosts(assignment, config, container_name, container_type,
                         inventory, is_metal):
    """Add a given container name and type to the hosts.

    :param assignment: ``str`` Name of container component target
    :param config: ``dict``  User defined information
    :param container_name: ``str``  Name fo container
    :param container_type: ``str``  Type of container
    :param inventory: ``dict``  Living dictionary of inventory
    :param is_metal: ``bol``  If true, a container entry will not be built
    """
    physical_host_type = '%s_hosts' % container_type.split('_')[0]
    # If the physical host type is not in config return
    if physical_host_type not in config:
        return

    for host_type in inventory[physical_host_type]['hosts']:
        container_hosts = inventory[container_name]['hosts']

        # If host_type is not in config do not append containers to it
        if host_type not in config[physical_host_type]:
            continue

        # Get any set host options
        host_options = config[physical_host_type][host_type]
        affinity = host_options.get('affinity', {})

        container_affinity = affinity.get(container_name, 1)
        # Ensures that container names are not longer than 63
        # This section will ensure that we are not it by the following bug:
        # https://bugzilla.mindrot.org/show_bug.cgi?id=2239
        type_and_name = '%s_%s' % (host_type, container_name)
        max_hostname_len = 52
        if len(type_and_name) > max_hostname_len:
            raise SystemExit(
                'The resulting combination of [ "%s" + "%s" ] is longer than'
                ' 52 characters. This combination will result in a container'
                ' name that is longer than the maximum allowable hostname of'
                ' 63 characters. Before this process can continue please'
                ' adjust the host entries in your "rpc_user_config.yml" to use'
                ' a short hostname. The recommended hostname length is < 20'
                ' characters long.' % (host_type, container_name)
            )

        physical_host = inventory['_meta']['hostvars'][host_type]
        container_host_type = '%s_containers' % host_type
        if 'container_types' not in physical_host:
            physical_host['container_types'] = container_host_type
        elif physical_host['container_types'] != container_host_type:
            physical_host['container_types'] = container_host_type

        # Add all of the containers into the inventory
        _build_container_hosts(
            container_affinity,
            container_hosts,
            type_and_name,
            inventory,
            host_type,
            container_type,
            container_host_type,
            physical_host_type,
            config,
            is_metal,
            assignment,
        )

        # Add the physical host type to all containers from the built inventory
        _append_container_types(inventory, host_type)
        _append_to_host_groups(
            inventory,
            container_type,
            assignment,
            host_type,
            type_and_name,
            host_options
        )


def user_defined_setup(config, inventory, is_metal):
    """Apply user defined entries from config into inventory.

    :param config: ``dict``  User defined information
    :param inventory: ``dict``  Living dictionary of inventory
    :param is_metal: ``bol``  If true, a container entry will not be built
    """
    for key, value in config.iteritems():
        if key.endswith('hosts'):
            if key not in inventory:
                inventory[key] = {'hosts': []}

            if value is None:
                return

            for _key, _value in value.iteritems():
                if _key not in inventory['_meta']['hostvars']:
                    inventory['_meta']['hostvars'][_key] = {}

                inventory['_meta']['hostvars'][_key].update({
                    'ansible_ssh_host': _value['ip'],
                    'container_address': _value['ip'],
                    'is_metal': is_metal,
                })

                if 'host_vars' in _value:
                    for _k, _v in _value['host_vars'].items():
                        inventory['_meta']['hostvars'][_key][_k] = _v

                append_if(array=USED_IPS, item=_value['ip'])
                append_if(array=inventory[key]['hosts'], item=_key)


def skel_setup(environment_file, inventory):
    """Build out the main inventory skeleton as needed.

    :param environment_file: ``dict`` Known environment information
    :param inventory: ``dict``  Living dictionary of inventory
    """
    for key, value in environment_file.iteritems():
        if key == 'version':
            continue
        for _key, _value in value.iteritems():
            if _key not in inventory:
                inventory[_key] = {}
                if _key.endswith('container'):
                    if 'hosts' not in inventory[_key]:
                        inventory[_key]['hosts'] = []
                else:
                    if 'children' not in inventory[_key]:
                        inventory[_key]['children'] = []
                    if 'hosts' not in inventory[_key]:
                        inventory[_key]['hosts'] = []

            if 'belongs_to' in _value:
                for assignment in _value['belongs_to']:
                    if assignment not in inventory:
                        inventory[assignment] = {}
                        if 'children' not in inventory[assignment]:
                            inventory[assignment]['children'] = []
                        if 'hosts' not in inventory[assignment]:
                            inventory[assignment]['hosts'] = []


def skel_load(skeleton, inventory):
    """Build out data as provided from the defined `skel` dictionary.

    :param skeleton:
    :param inventory: ``dict``  Living dictionary of inventory
    """
    for key, value in skeleton.iteritems():
        _parse_belongs_to(
            key,
            belongs_to=value['belongs_to'],
            inventory=inventory
        )


def _load_optional_q(config, cidr_name):
    """Load optional queue with ip addresses.

    :param config: ``dict``  User defined information
    :param cidr_name: ``str``  Name of the cidr name
    """
    cidr = config.get(cidr_name)
    ip_q = None
    if cidr is not None:
        ip_q = Queue.Queue()
        _load_ip_q(cidr=cidr, ip_q=ip_q)
    return ip_q


def _add_additional_networks(key, inventory, ip_q, q_name, netmask, interface,
                             bridge, net_type, user_config, is_ssh_address,
                             is_container_address):
    """Process additional ip adds and append then to hosts as needed.

    If the host is found to be "is_metal" it will be marked as "on_metal"
    and will not have an additionally assigned IP address.

    :param key: ``str`` Component key name.
    :param inventory: ``dict``  Living dictionary of inventory.
    :param ip_q: ``object`` build queue of IP addresses.
    :param q_name: ``str`` key to use in host vars for storage.
    :param netmask: ``str`` netmask to use.
    :param interface: ``str`` interface name to set for the network.
    :param user_config: ``dict`` user defined configuration details.
    :param is_ssh_address: ``bol`` set this address as ansible_ssh_host.
    :param is_container_address: ``bol`` set this address to container_address.
    """

    def network_entry():
        """Return a network entry for a container."""

        # TODO(cloudnull) After a few releases this conditional should be
        # simplified. The container address checking that is ssh address
        # is only being done to support old inventory.

        if is_metal:
            _network = dict()
        else:
            _network = {'interface': interface}

        if bridge:
            _network['bridge'] = bridge

        if net_type:
            _network['type'] = net_type

        return _network

    def return_netmask():
        """Return the netmask for a container."""

        # TODO(cloudnull) After a few releases this conditional should be
        # simplified. The container address checking that is ssh address
        # is only being done to support old inventory.
        _old_netmask = container.get(old_netmask)
        if _old_netmask:
            return container.pop(old_netmask)
        elif netmask:
            return netmask

    base_hosts = inventory['_meta']['hostvars']
    lookup = inventory.get(key, list())

    if 'children' in lookup and lookup['children']:
        for group in lookup['children']:
            _add_additional_networks(
                group,
                inventory,
                ip_q,
                q_name,
                netmask,
                interface,
                bridge,
                net_type,
                user_config,
                is_ssh_address,
                is_container_address
            )

    hosts = lookup.get('hosts')
    if not hosts:
        return

    # TODO(cloudnull) after a few releases this should be removed.
    old_address = '%s_address' % q_name
    old_netmask = '%s_netmask' % q_name

    for container_host in hosts:
        container = base_hosts[container_host]

        # TODO(cloudnull) after a few releases this should be removed.
        # This removes the old container network value that now serves purpose.
        container.pop('container_network', None)

        if 'container_networks' in container:
            networks = container['container_networks']
        else:
            networks = container['container_networks'] = dict()

        is_metal = container.get('is_metal')

        ## This should convert found addresses based on q_name + "_address"
        #  and then build the network if its not found.
        if not is_metal and old_address not in networks:
            network = networks[old_address] = network_entry()
            if old_address in container and container[old_address]:
                network['address'] = container.pop(old_address)
            elif not is_metal:
                address = get_ip_address(name=q_name, ip_q=ip_q)
                if address:
                    network['address'] = address

            network['netmask'] = return_netmask()
        elif is_metal:
            network = networks[old_address] = network_entry()
            network['netmask'] = return_netmask()
            # TODO(cloudnull) After a few releases this conditional should be
            # simplified. The container address checking that is ssh address
            # is only being done to support old inventory.
            if old_address in container and container[old_address]:
                network['address'] = container.pop(old_address)
            else:
                if is_ssh_address or is_container_address:
                    # Container physical host group
                    cphg = container.get('physical_host_group')
                    # user_config data from the container physical host group
                    phg = user_config[cphg][container_host]
                    network['address'] = phg['ip']

        if is_ssh_address is True:
            container['ansible_ssh_host'] = networks[old_address]['address']

        if is_container_address is True:
            container['container_address'] = networks[old_address]['address']


def container_skel_load(container_skel, inventory, config):
    """Build out all containers as defined in the environment file.

    :param container_skel: ``dict`` container skeleton for all known containers
    :param inventory: ``dict``  Living dictionary of inventory
    :param config: ``dict``  User defined information
    """
    for key, value in container_skel.iteritems():
        for assignment in value['contains']:
            for container_type in value['belongs_to']:
                _add_container_hosts(
                    assignment,
                    config,
                    key,
                    container_type,
                    inventory,
                    value.get('is_metal', False)
                )
    else:
        cidr_networks = config.get('cidr_networks')
        provider_queues = {}
        for net_name in cidr_networks:
            ip_q = _load_optional_q(
                cidr_networks, cidr_name=net_name
            )
            provider_queues[net_name] = ip_q
            if ip_q is not None:
                net = netaddr.IPNetwork(cidr_networks.get(net_name))
                provider_queues['%s_netmask' % net_name] = str(net.netmask)

        overrides = config['global_overrides']
        # iterate over a list of provider_networks, var=pn
        for pn in overrides.get('provider_networks', list()):
            # p_net are the provider_network values
            p_net = pn.get('network')
            if not p_net:
                continue

            q_name = p_net.get('ip_from_q')
            ip_from_q = provider_queues.get(q_name)
            if ip_from_q:
                netmask = provider_queues['%s_netmask' % q_name]
            else:
                netmask = None

            for group in p_net.get('group_binds', list()):
                _add_additional_networks(
                    key=group,
                    inventory=inventory,
                    ip_q=ip_from_q,
                    q_name=q_name,
                    netmask=netmask,
                    interface=p_net['container_interface'],
                    bridge=p_net['container_bridge'],
                    net_type=p_net.get('container_type'),
                    user_config=config,
                    is_ssh_address=p_net.get('is_ssh_address'),
                    is_container_address=p_net.get('is_container_address')
                )


def file_find(pass_exception=False, user_file=None):
    """Return the path to a file.

    If no file is found the system will exit.
    The file lookup will be done in the following directories:
      /etc/rpc_deploy/
      $HOME/rpc_deploy/
      $(pwd)/rpc_deploy/

    :param pass_exception: ``bol``
    :param user_file: ``str`` Additional location to look in FIRST for a file
    """

    file_check = [
        os.path.join('/etc', 'rpc_deploy'),
        os.path.join(os.environ.get('HOME'), 'rpc_deploy')
    ]

    if user_file is not None:
        file_check.insert(0, os.path.expanduser(user_file))

    for f in file_check:
        if os.path.isdir(f):
            return f
    else:
        if pass_exception is False:
            raise SystemExit('No file found at: %s' % file_check)
        else:
            return False


def _set_used_ips(user_defined_config, inventory):
    """Set all of the used ips into a global list.

    :param user_defined_config: ``dict`` User defined configuration
    :param inventory: ``dict`` Living inventory of containers and hosts
    """
    used_ips = user_defined_config.get('used_ips')
    if isinstance(used_ips, list):
        for ip in used_ips:
            split_ip = ip.split(',')
            if len(split_ip) >= 2:
                ip_range = list(
                    netaddr.iter_iprange(
                        split_ip[0],
                        split_ip[-1]
                    )
                )
                USED_IPS.extend([str(i) for i in ip_range])
            else:
                append_if(array=USED_IPS, item=split_ip[0])

    # Find all used IP addresses and ensure that they are not used again
    for host_entry in inventory['_meta']['hostvars'].values():
        if 'ansible_ssh_host' in host_entry:
            append_if(array=USED_IPS, item=host_entry['ansible_ssh_host'])

        for key, value in host_entry.iteritems():
            if key.endswith('address'):
                append_if(array=USED_IPS, item=value)


def _ensure_inventory_uptodate(inventory):
    """Update inventory if needed.

    Inspect the current inventory and ensure that all host items have all of
    the required entries.

    :param inventory: ``dict`` Living inventory of containers and hosts
    """
    for key, value in inventory['_meta']['hostvars'].iteritems():
        if 'container_name' not in value:
            value['container_name'] = key

        for rh in REQUIRED_HOSTVARS:
            if rh not in value:
                value[rh] = None


def _parse_global_variables(user_cidr, inventory, user_defined_config):
    """Add any extra variables that may have been set in config.

    :param user_cidr: ``str`` IP address range in CIDR notation
    :param inventory: ``dict`` Living inventory of containers and hosts
    :param user_defined_config: ``dict`` User defined variables
    """
    if 'all' not in inventory:
        inventory['all'] = {}

    if 'vars' not in inventory['all']:
        inventory['all']['vars'] = {}

    # Write the users defined cidr into global variables.
    inventory['all']['vars']['container_cidr'] = user_cidr

    if 'global_overrides' in user_defined_config:
        if isinstance(user_defined_config['global_overrides'], dict):
            inventory['all']['vars'].update(
                user_defined_config['global_overrides']
            )


def append_if(array, item):
    """Append an ``item`` to an ``array`` if its not already in it.

    :param array: ``list``  List object to append to
    :param item: ``object``  Object to append to the list
    :returns array:  returns the amended list.
    """
    if item not in array:
        array.append(item)
    return array


def md5_checker(localfile):
    """Check for different Md5 in CloudFiles vs Local File.

    If the md5 sum is different, return True else False

    :param localfile:
    :return True|False:
    """

    def calc_hash():
        """Read the hash.

        :return data_hash.read():
        """

        return data_hash.read(128 * md5.block_size)

    if os.path.isfile(localfile) is True:
        md5 = hashlib.md5()
        with open(localfile, 'rb') as data_hash:
            for chk in iter(calc_hash, ''):
                md5.update(chk)

        return md5.hexdigest()
    else:
        raise SystemExit('This [ %s ] is not a file.' % localfile)


def _merge_dict(base_items, new_items):
    """Recursively merge new_items into some base_items.

    :param base_items: ``dict``
    :param new_items: ``dict``
    :return dictionary:
    """
    for key, value in new_items.iteritems():
        if isinstance(value, dict):
            base_merge = _merge_dict(base_items.get(key, {}), value)
            base_items[key] = base_merge
        else:
            base_items[key] = new_items[key]
    return base_items


def _extra_config(user_defined_config, base_dir):
    """Discover new items in a conf.d directory and add the new values.

    :param user_defined_config: ``dict``
    :param base_dir: ``str``
    """
    for root_dir, _, files in os.walk(base_dir):
        for name in files:
            if name.endswith(('.yml', '.yaml')):
                with open(os.path.join(root_dir, name), 'rb') as f:
                    _merge_dict(
                        user_defined_config,
                        yaml.safe_load(f.read()) or {}
                    )


def main():
    """Run the main application."""
    all_args = args()
    user_defined_config = dict()

    # Get the local path
    local_path = file_find(
        user_file=all_args.get('file')
    )

    # Load the user defined configuration file
    user_config_file = os.path.join(local_path, 'rpc_user_config.yml')
    if os.path.isfile(user_config_file):
        with open(user_config_file, 'rb') as f:
            user_defined_config.update(yaml.safe_load(f.read()) or {})

    # Load anything in a conf.d directory if found
    base_dir = os.path.join(local_path, 'conf.d')
    if os.path.isdir(base_dir):
        _extra_config(user_defined_config, base_dir)

    # Exit if no user_config was found and loaded
    if not user_defined_config:
        raise SystemExit(
            'No user config loadaed\n'
            'No rpc_user_config files are available in either the base'
            ' location or the conf.d directory'
        )

    # Get the contents of the system environment json
    environment_file = os.path.join(local_path, 'rpc_environment.yml')

    # Load existing rpc environment json
    with open(environment_file, 'rb') as f:
        environment = yaml.safe_load(f.read())

    # Check the version of the environment file
    env_version = md5_checker(localfile=environment_file)
    version = user_defined_config.get('environment_version')
    if env_version != version:
        raise SystemExit(
            'The MD5 sum of the environment file does not match the expected'
            ' value. To ensure that you are using the proper environment'
            ' please repull the correct environment file from the upstream'
            ' repository. Found MD5: [ %s ] expected MD5 [ %s ]'
            % (env_version, version)
        )

    # Load existing inventory file if found
    dynamic_inventory_file = os.path.join(local_path, 'rpc_inventory.json')
    if os.path.isfile(dynamic_inventory_file):
        with open(dynamic_inventory_file, 'rb') as f:
            dynamic_inventory = json.loads(f.read())

        # Create a backup of all previous inventory files as a tar archive
        inventory_backup_file = os.path.join(
            local_path,
            'backup_rpc_inventory.tar'
        )
        with tarfile.open(inventory_backup_file, 'a') as tar:
            basename = os.path.basename(dynamic_inventory_file)
            # Time stamp the inventory file in UTC
            utctime = datetime.datetime.utcnow()
            utctime = utctime.strftime("%Y%m%d_%H%M%S")
            backup_name = '%s-%s.json' % (basename, utctime)
            tar.add(dynamic_inventory_file, arcname=backup_name)
    else:
        dynamic_inventory = INVENTORY_SKEL

    # Save the users container cidr as a group variable
    cidr_networks = user_defined_config.get('cidr_networks')
    if not cidr_networks:
        raise SystemExit('No container CIDR specified in user config')

    if 'container' in cidr_networks:
        user_cidr = cidr_networks['container']
    elif 'management' in cidr_networks:
        user_cidr = cidr_networks['management']
    else:
        raise SystemExit('No container or management network specified')

    # Add the container_cidr into the all global ansible group_vars
    _parse_global_variables(user_cidr, dynamic_inventory, user_defined_config)

    # Load all of the IP addresses that we know are used and set the queue
    _set_used_ips(user_defined_config, dynamic_inventory)
    user_defined_setup(user_defined_config, dynamic_inventory, is_metal=True)
    skel_setup(environment, dynamic_inventory)
    skel_load(
        environment.get('physical_skel'),
        dynamic_inventory
    )
    skel_load(
        environment.get('component_skel'), dynamic_inventory
    )
    container_skel_load(
        environment.get('container_skel'),
        dynamic_inventory,
        user_defined_config
    )

    # Look at inventory and ensure all entries have all required values.
    _ensure_inventory_uptodate(inventory=dynamic_inventory)

    # Load the inventory json
    dynamic_inventory_json = json.dumps(
        dynamic_inventory,
        indent=4,
        sort_keys=True
    )

    # Generate a list of all hosts and their used IP addresses
    hostnames_ips = {}
    for _host, _vars in dynamic_inventory['_meta']['hostvars'].iteritems():
        host_hash = hostnames_ips[_host] = {}
        for _key, _value in _vars.iteritems():
            if _key.endswith('address') or _key == 'ansible_ssh_host':
                host_hash[_key] = _value

    # Save a list of all hosts and their given IP addresses
    with open(os.path.join(local_path, 'rpc_hostnames_ips.yml'), 'wb') as f:
        f.write(
            json.dumps(
                hostnames_ips,
                indent=4
            )
        )

    # Save new dynamic inventory
    with open(dynamic_inventory_file, 'wb') as f:
        f.write(dynamic_inventory_json)

    # Print out our inventory
    print(dynamic_inventory_json)

if __name__ == '__main__':
    main()
