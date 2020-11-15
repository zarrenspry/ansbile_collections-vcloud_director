# Ansible Collection - zarrenspry.vcloud_director

This repo contains a collection of modules that can be used with VMWare vCloud.

All of the modules are in the Alpha stages of development. Expect issues!

# Prerequisites

pyvcloud is required for this collection.
netaddr is required for this collection.
Python => 3.6 is required for this collection.

# Using this collection

You can install this collection using the following command.

```console
foo@bar:~$ ansible-galaxy collection install git+https://github.com/zarrenspry/ansbile_collections-vcloud_director.git
```

## vCloud Dynamic inventory plugin

This is an inventory plug in that can use metadata from VMWare assets 
to aggregate hosts into groups and also filter on. It also imports 
power status and os_type into host_vars. 

### group_keys

*group_keys* can be used to aggregate hosts into groups. Supply a YAML
list and the script will look for those keys, create the groups and add
any host that has that key/value set in it's metadata.

Although everything within a returned Key/Value pair is a string,
I've added the ability to work with composite data. Only lists are 
supported for now. If the script encounters a value that contains a list
it will attempt to break down the list and create groups from that data.

### filters
 *filters* can be used to look for key/value pairs within the metadata
 and filter out those targets. For example, if I added *env: Production*
 to filters, only vms with the key **env** present and with the value 
 **Production** will be added to the inventory.
 
### Example

- Config
```yaml
# vcloud.yml
plugin: zarrenspry.vcloud_director.vcloud_director_inventory
user: "a_user"
password: "a_strong_password"
host: "https://vcd.vmware.local"
org: "an_org"
cidr: "192.168.1.0/24"
target_vdc: "a_vdc"
cache: true
filters:
  env: Development
group_keys:
  - type
``` 

- result
```json
{
  "Development": {
    "hosts": [
      "web_1",
      "app_1",
      "app_2"
    ]
  },
  "_meta": {
    "hostvars": {
        "web_1": {
          "ansible_host": "192.168.1.1",
          "os_type": "centos7_64Guest",
          "power_state": "Powered on",
          "cpu_hot_enabled": true,
          "hardware_version": "vmx-13",
          "memory_hot_enabled": true,
          "storage_profile": "Standard",
          "virtual_machine_id": "78bdcc54-81b6-4fa9-b055-898f9362b5cc",
          "vmware_tools_version": "10346"
        }
    },
    "hostvars": {
        "app_1": {
          "ansible_host": "192.168.1.2",
          "os_type": "centos7_64Guest",
          "power_state": "Powered on",
          "cpu_hot_enabled": true,
          "hardware_version": "vmx-13",
          "memory_hot_enabled": true,
          "storage_profile": "Standard",
          "virtual_machine_id": "25e58eca-d16d-4357-a579-5c2b080c2e99",
          "vmware_tools_version": "10346"
        }
    },
    "hostvars": {
        "app_2": {
          "ansible_host": "192.168.1.3",
          "os_type": "centos7_64Guest",
          "power_state": "Powered on",
          "cpu_hot_enabled": true,
          "hardware_version": "vmx-13",
          "memory_hot_enabled": true,
          "storage_profile": "Standard",
          "virtual_machine_id": "11a03a6d-3257-4c0d-a282-0bbcced1cc18",
          "vmware_tools_version": "10346"
        }
     }
  },
  "discovered": { 
    "hosts": [
      "web_1",
      "app_1",
      "app_2"
    ]
  }
}
```
### TODO
- Code cleanup
- Write some unit tests

### DONE
- Caching now works

### Maybe?
- Threading?