# Copyright (c) 2020 Zarren Spry <zarrenspry@gmail.com>
# Apache License v2.0

# !/usr/bin/python

ANSIBLE_METADATA = {
    'metadata_version': '1.1',
    'status': ['preview'],
    'supported_by': 'community'
}

DOCUMENTATION = '''
    name: vcloud_director_inventory
    plugin_type: inventory
    short_description: vCloud Director inventory source
    version_added: "2.10"
    requirements:
        - pyvcloud
    extends_documentation_fragment:
        - inventory_cache
        - constructed
    description:
        - Get inventory hosts from VMWare vCloud source
        - Uses a YAML configuration file that ends with C(vCloud_director.(yml|yaml)).
    notes:
        - Privileged account required to run
    author:
        - Zarren Spry <zarrenspry@gmail.com>
    options:
        plugin:
            description: Token that ensures this is a source file for the plugin.
            required: True
            choices: ['vcloud_director_inventory']
        user:
            description:
                - vCloud Director user name
            required: false
        password:
            description:
                - vCloud Director user password
            required: false
        host:
            description:
                - vCloud Director host address
            required: false
        org:
            description:
                - Organization name on vCloud Director to access
            required: false
        api_version:
            description:
                - Pyvcloud API version
            required: false
        verify_ssl_certs:
            description:
                - whether to use secure connection to vCloud Director host
            required: false
        cidr:
            description:
                - CIDR range to be used when grabbing the machine IP
            required: false
        target_vdc:
            description:
                - Target Virtual DataCenter name
            required: false
        root_group:
            description:
                - Root group name
            required: false
        group_keys:
            description:
                - List of keys to search for within the host metadata and create groups.
                - Can consume types list and string.
            required: false
        filters:
            description:
                - key/value pairs to look for and filter upon..
            required: false
        set_cache:
            description:
                - Enable inventory caching
'''

EXAMPLES = '''
# vcloud.yml
plugin: zarrenspry.vcloud_director.vcloud_director_inventory
user: "a_user"
password: "a_strong_password"
host: "https://vcd.vmware.local"
org: "an_org"
cidr: "192.168.1.0/24"
target_vdc: "a_vdc"
root_group: discovered
filters:
  version: 0.0.1
group_keys:
  - env
'''

from ansible.plugins.inventory import (
    BaseInventoryPlugin,
    Constructable,
    Cacheable
)
from ansible.errors import AnsibleError

from netaddr import IPNetwork

from pyvcloud.vcd.client import (
    EntityType,
    BasicLoginCredentials,
    Client
)
from pyvcloud.vcd.org import Org
from pyvcloud.vcd.vapp import VApp
from pyvcloud.vcd.vdc import VDC
from pyvcloud.vcd.vm import VM
from pyvcloud.vcd.client import VCLOUD_STATUS_MAP

import re


class InventoryModule(BaseInventoryPlugin, Constructable, Cacheable):
    NAME = 'zarrenspry.vcloud_director.vcloud_director_inventory'

    def __init__(self):

        super().__init__()
        self.client = None
        self.vdc = None
        self.org = None
        self.group_keys = []
        self.machines = []
        self.inventory = None
        self.vapp_resource = None
        self.root_group = None

        self.cache_needs_update = False
        self.cache_key = None

    def _authenticate(self):
        try:
            self.client = Client(self.get_option('host'),
                                 api_version=self.get_option('api_version'),
                                 verify_ssl_certs=self.get_option('verify_ssl_certs')
                                 )
            self.client.set_credentials(
                BasicLoginCredentials(
                    self.get_option('user'),
                    self.get_option('org'),
                    self.get_option('password')
                )
            )
        except Exception as e:
            raise AnsibleError(f"Failed to login to endpoint. MSG: {e}")

    def _get_org(self):
        try:
            self.org = Org(self.client, resource=self.client.get_org())
        except Exception as e:
            raise AnsibleError(f"Failed to create Org object. MSG: {e}")

    def _get_vdc(self):
        self._authenticate()
        self._get_org()
        try:
            self.vdc = VDC(self.client, resource=self.org.get_vdc(self.get_option('target_vdc')))
        except Exception as e:
            raise AnsibleError(f"Failed to create VDC object. MSG: {e}")

    def _get_vapps(self):
        self._get_vdc()
        try:
            return self.vdc.list_resources(EntityType.VAPP)
        except Exception as e:
            raise AnsibleError(f"Failed to get all vapp resources, MSG:: {e}")

    def _get_vapp_resource(self, name):
        try:
            return VApp(self.client, resource=self.vdc.get_vapp(name))
        except Exception as e:
            raise AnsibleError(f"Failed to get vApp resource, MSG: {e}")

    def _get_vm_resource(self, vm):
        try:
            return VM(self.client, resource=self.vapp_resource.get_vm(vm))
        except Exception as e:
            raise AnsibleError(f"Failed to get vm resource, MSG: {e}")

    def _add_host(self, machine):
        name, ip = machine.get('name'), machine.get('ip')
        self.display.vvvv(f"Adding {name}:{ip} to inventory.")
        self.inventory.add_host(name, self.root_group)
        self.inventory.set_variable(name, 'ansible_host', ip)
        for meta in machine.keys():
            if meta not in ["metadata", "name", "ip"]:
                self.inventory.set_variable(name, meta, machine.get(meta))

    def _add_group(self, machine, group_keys):
        for key in group_keys:
            if key in machine.get('metadata').keys():
                data = machine.get('metadata').get(key)
                # Is this composite data ?
                if re.match('\[["\']\w+["\'],.*\]', data):
                    self.display.vvvv(f"Composite data found within {key}")
                    for group in re.findall('[a-zA-Z_]+', data):
                        if group != self.root_group and re.match('[\w_]', group):
                            self.display.vvvv(f"Adding {machine.get('name')}:{machine.get('ip')} to group {group}")
                            self.inventory.add_group(group)
                            self.inventory.add_child(group, machine.get('name').lower())
                else:
                    if data != self.root_group:
                        self.display.vvvv(f"Adding {machine.get('name')}:{machine.get('ip')} to group {data}")
                        self.inventory.add_group(data)
                        self.inventory.add_child(data, machine.get('name').lower())

    def _query(self, vm):
        vm_name = str(vm.get('name')).lower().replace("-", "_").replace(".", "")
        vm_ip = None
        metadata = {}

        for network in vm.NetworkConnectionSection:
            for connection in network.NetworkConnection:
                if connection.IpAddress in [str(i) for i in list(IPNetwork(self.get_option('cidr')))]:
                    vm_ip = str(connection.IpAddress)

        vm_resource = self._get_vm_resource(vm.get('name'))
        for meta in vm_resource.get_metadata():
            if hasattr(meta, "MetadataEntry"):
                metadata = {i.Key.pyval: i.TypedValue.Value.pyval for i in meta.MetadataEntry}

        if vm_ip:
            self.machines.append({
                'name': vm_name,
                'ip': vm_ip,
                'metadata': metadata,
                'os_type': str(vm.VmSpecSection[0].OsType),
                'power_state': VCLOUD_STATUS_MAP[int(vm.get('status'))],
                'hardware_version': str(vm.VmSpecSection[0].HardwareVersion),
                'vmware_tools_version': str(vm.VmSpecSection[0].VmToolsVersion),
                'virtual_machine_id': str(vm.GuestCustomizationSection[0].VirtualMachineId),
                'memory_hot_enabled': str(vm.VmCapabilities[0].MemoryHotAddEnabled),
                'cpu_hot_enabled': str(vm.VmCapabilities[0].CpuHotAddEnabled),
                'storage_profile': str(vm.StorageProfile.get("name"))
            })

    def _populate(self, machine):
        group_keys = self.get_option('group_keys')
        filters = self.get_option('filters')
        if filters:
            for _ in machine.get('metadata').items() & filters.items():
                self._add_host(machine)
                if group_keys:
                    self._add_group(machine, group_keys)
        else:
            self._add_host(machine)
            if group_keys:
                self._add_group(machine, group_keys)

    def _config_cache(self, cache):
        self.load_cache_plugin()
        if cache:
            try:
                self.machines = self._cache[self.cache_key]
            except KeyError:
                self.cache_needs_update = True

    def verify_file(self, path):
        valid = False
        if super().verify_file(path):
            if path.endswith(('vcloud.yaml', 'vcloud.yml')):
                valid = True
        return valid

    def parse(self, inventory, loader, path, cache=True):

        super().parse(inventory, loader, path)

        self._read_config_data(path)
        self.inventory = inventory
        self.root_group = self.get_option('root_group')

        self.inventory.add_group(self.root_group)
        self.cache_key = self.get_cache_key(path)

        cache = self.get_option('set_cache')
        self._config_cache(cache)

        if not cache or self.cache_needs_update:
            for vapp in self._get_vapps():
                self.vapp_resource = self._get_vapp_resource(vapp.get('name'))
                vms = self.vapp_resource.get_all_vms()
                for vm in vms:
                    self._query(vm)
            try:
                self._cache[self.cache_key] = self.machines
            except Exception as e:
                raise AnsibleError(f"Failed to populate data: {e}")
        for machine in self.machines:
            self._populate(machine)
