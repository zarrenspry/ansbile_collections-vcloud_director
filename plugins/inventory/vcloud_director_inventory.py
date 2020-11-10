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
                - List of keys to search for within the host metadata and create groups
            required: false
        filters:
            description:
                - key/value pairs to look for and filter upon..
            required: false
        set_cache:
            description:
                - Enable inventory caching
        flush_cache:
            description:
                - Set true to flush the cache
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

from threading import Thread

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


class InventoryModule(BaseInventoryPlugin, Constructable, Cacheable):
    NAME = 'zarrenspry.vcloud_director.vcloud_director_inventory'

    def __init__(self):

        super().__init__()
        self.client = None
        self.vdc = None
        self.org = None
        self.group_keys = []
        self.assets = []

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
            raise AnsibleError("Failed to login to endpoint. MSG: {e}")

    def _get_org(self):
        try:
            self.org = Org(self.client, resource=self.client.get_org())
        except Exception as e:
            raise AnsibleError("Failed to create Org object. MSG: {e}")

    def _get_vdc(self):
        try:
            self.vdc = VDC(self.client, resource=self.org.get_vdc(self.get_option('target_vdc')))
        except Exception as e:
            raise AnsibleError("Failed to create VDC object. MSG: {e}")

    def _get_vapps(self):
        return self.vdc.list_resources(EntityType.VAPP)

    def _get_vapp_resource(self, name):
        return VApp(self.client, resource=self.vdc.get_vapp(name))

    def _get_vm_resource(self, vapp, vm):
        return VM(self.client, resource=vapp.get_vm(vm))

    def _add_host(self, inventory, asset):
        self.display.vvvv(f"Adding {asset.get('name')}:{asset.get('ip')} to inventory.")
        inventory.add_host(asset.get('name'), self.get_option('root_group'))
        inventory.set_variable(asset.get('name'), 'ansible_host', asset.get('ip'))
        inventory.set_variable(asset.get('name'), 'os_type', asset.get('os_type'))
        inventory.set_variable(asset.get('name'), 'power_state', asset.get('power_state'))

    def _add_group(self, asset, group_keys, inventory):
        metadata = asset.get('metadata')
        for key in group_keys:
            if key in metadata.keys():
                self.display.vvvv(f"Adding {asset.get('name')}:{asset.get('ip')} to sub-group {metadata.get(key)}")
                inventory.add_group(metadata.get(key).lower())
                inventory.add_child(metadata.get(key).lower(), asset.get('name').lower())

    def _query(self, vm, vapp_resource):
        global vm_ip
        global vm_name
        global os_type

        vm_name = str(vm.get('name')).lower().replace("-", "_")
        os_type = str(vm.VmSpecSection[0].OsType)

        for network in vm.NetworkConnectionSection:
            for connection in network.NetworkConnection:
                if connection.IpAddress in [str(i) for i in list(IPNetwork(self.get_option('cidr')))]:
                    vm_ip = str(connection.IpAddress)
                    break
        vm_resource = self._get_vm_resource(vapp_resource, vm.get('name'))
        for meta in vm_resource.get_metadata():
            if hasattr(meta, "MetadataEntry"):
                metadata = {str(i.Key): str(i.TypedValue.Value) for i in meta.MetadataEntry}
            else:
                metadata = {}
        self.assets.append({
            'name': vm_name,
            'ip': vm_ip,
            'metadata': metadata,
            'os_type': os_type,
            'power_state': VCLOUD_STATUS_MAP[int(vm.get('status'))]
        })
        self.display.vvvv(f"vm {vm_name} found, ip: {vm_ip}")

    def _populate(self, data, inventory):
        for asset in data:
            filters = self.get_option('filters')
            group_keys = self.get_option('group_keys')
            if filters:
                for _ in asset.get('metadata').items() & filters.items():
                    self._add_host(inventory, asset)
                    if group_keys:
                        self._add_group(asset, group_keys, inventory)
            else:
                self._add_host(inventory, asset)
                if group_keys:
                    self._add_group(asset, group_keys, inventory)

    def _cache(self):
        pass

    def verify_file(self, path):
        valid = False
        if super().verify_file(path):
            if path.endswith(('vcloud.yaml', 'vcloud.yml')):
                valid = True
        return valid

    def parse(self, inventory, loader, path, cache=True):

        super().parse(inventory, loader, path)
        self._read_config_data(path)

        inventory.add_group(self.get_option('root_group'))

        self._authenticate()
        self._get_org()
        self._get_vdc()

        self.load_cache_plugin()

        cache_key = self.get_cache_key(path)
        cache = self.get_option('set_cache')
        flush_cache = self.get_option('flush_cache')
        cache_needs_update = False

        if flush_cache:
            try:
                self.clear_cache()
            except Exception as e:
                raise AnsibleError(f"Failed to flush cache: {e}")
        if cache:
            try:
                results = self._cache[cache_key]
            except KeyError as e:
                cache_needs_update = True

        if not cache or cache_needs_update:
            threads = []
            vapps = self._get_vapps()
            for vapp in vapps:
                vapp_resource = self._get_vapp_resource(vapp.get('name'))
                vms = vapp_resource.get_all_vms()
                for vm in vms:
                    thread = Thread(target=self._query, args=(vm, vapp_resource,))
                    thread.daemon = True
                    thread.start()
                    threads.append(thread)
            for process in threads:
                process.join()

            results = self.assets

        self._populate(results, inventory)

        try:
            if cache_needs_update or (not cache and self.get_option('cache')):
                self._cache[cache_key] = results
        except Exception as e:
            raise AnsibleError(f"Failed to populate data: {e}")
