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
        cache:
            description:
                - Set cache
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
root_group: all
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

    def _get_vapps(self):
        """ Returns a list of vApp resources
        Keyword arguments:
        target (String): Name of the target vDC
        """
        return self.vdc.list_resources(EntityType.VAPP)

    def _get_vapp_resource(self, name):
        return VApp(self.client, resource=self.vdc.get_vapp(name))

    def _get_vm_resource(self, vapp, vm):
        return VM(self.client, resource=vapp.get_vm(vm))

    def _add_host(self, inventory, asset, root_group_name):
        self.display.vvvv(f"Adding {asset.get('name')}:{asset.get('ip')} to inventory.")
        inventory.add_host(asset.get('name'), root_group_name)
        inventory.set_variable(asset.get('name'), 'ansible_host', asset.get('ip'))
        inventory.set_variable(asset.get('name'), 'os_type', asset.get('os_type'))
        inventory.set_variable(asset.get('name'), 'power_state', asset.get('power_state'))

    def _add_group(self, asset, group_keys, inventory):
        metadata = asset.get('metadata')
        for key in group_keys:
            if key in metadata.keys():
                self.display.vvvv(f"Adding {asset.get('name')}:{asset.get('ip')} to sub-group {metadata.get(key)}")
                inventory.add_group(metadata.get(key))
                inventory.add_child(metadata.get(key), asset.get('name'))

    def parse(self, inventory, loader, path, cache=True):

        super(InventoryModule, self).parse(inventory, loader, path, cache)

        self.load_cache_plugin()
        cache_key = self.get_cache_key(path)

        user_cache_setting = self.get_option('cache')
        attempt_to_read_cache = user_cache_setting and cache
        cache_needs_update = user_cache_setting and not cache
        if attempt_to_read_cache:
            try:
                results = self._cache[cache_key]
            except KeyError:
                cache_needs_update = True

        if cache_needs_update:
            results = self.get_inventory()

            # set the cache
            self._cache[cache_key] = results

        self._read_config_data(path)

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
            _logged_in_org = self.client.get_org()
            org = Org(self.client, resource=_logged_in_org)
            self.vdc = VDC(self.client, resource=org.get_vdc(self.get_option('target_vdc')))

        except Exception as e:
            AnsibleError(f"Failed to login to endpoint. MSG: {e}")

        assets = []
        for vapp in self._get_vapps():
            vapp_resource = self._get_vapp_resource(vapp.get('name'))
            inventory.add_group(self.get_option('root_group'))
            for vm in vapp_resource.get_all_vms():
                # Grab the machine name
                vm_name = str(vm.get('name')).replace("-", "_")
                # Grab the first IP that corresponds to the provided CIDR range
                for network in vm.NetworkConnectionSection:
                    for connection in network.NetworkConnection:
                        if connection.IpAddress in [str(i) for i in list(IPNetwork(self.get_option('cidr')))]:
                            vm_ip = str(connection.IpAddress)
                            break
                # Get a vm resource to use for metadata collection
                vm_resource = self._get_vm_resource(vapp_resource, vm.get('name'))
                # Build dict from Metadata key/value pairs
                for meta in vm_resource.get_metadata():
                    if hasattr(meta, "MetadataEntry"):
                        metadata = {str(i.Key): str(i.TypedValue.Value) for i in meta.MetadataEntry}
                    else:
                        metadata = {}
                assets.append({
                    'name': vm_name,
                    'ip': vm_ip,
                    'metadata': metadata,
                    'os_type': str(vm.VmSpecSection[0].OsType),
                    'power_state': VCLOUD_STATUS_MAP[int(vm.get('status'))]
                })
                self.display.vvvv(f"vm {vm_name} found, ip: {vm_ip}")

        filters = self.get_option('filters')
        group_keys = self.get_option('group_keys')
        for asset in assets:
            if filters:
                for k, v in asset.get('metadata').items() & filters.items():
                    if k in asset.get('metadata'):
                        self._add_host(inventory, asset, self.get_option('root_group'))
                        if group_keys:
                            self._add_group(asset, group_keys, inventory)
            else:
                self._add_host(inventory, asset, self.get_option('root_group'))
                if group_keys:
                    self._add_group(asset, group_keys, inventory)
