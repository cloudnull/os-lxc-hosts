Rackspace Private Cloud Container Hosts
#######################################
:date: 2014-09-25 09:00
:tags: rackspace, lxc, openstack, cloud, ansible
:category: \*nix


Official Documentation
----------------------

Comprehensive installation guides, including FAQs and release notes, can be found at http://docs.rackspace.com

Playbook Support
----------------

There are several playbooks within that will setup hosts for use in Rackspace Private Cloud. The playbooks will enable LXC on hosts and provides the ability to deploy LXC containers for use within openstack.

Plays:
  * ``host-setup.yml``  Performs host setup for use with LXC in the Rackspace Private Cloud. This run the plays ``lxc-host-setup.yml`` and ``lxc-lib-install.yml``.
  * ``lxc-host-setup.yml`` Sets up hosts to run containers.
  * ``lxc-lib-install.yml`` Installs the required Python2 lxc library.
  * ``containers-create.yml``  Creates all containers.
  * ``containers-destroy.yml``  Destroys **ALL** known containers on **ALL** defined hosts.


Setup:
  1. Run the ``bootstrap.sh`` script, which will install, pip, ansible 1.8.x, and all of the required python packages.
  2. Copy the etc/opc_deploy directory to /etc/opc_deploy
  3. Fill in your ``/etc/opc_deploy/opc_user_config.yml``, ``/etc/opc_deploy/user_secrets.yml`` and ``/etc/opc_deploy/user_variables.yml`` files.
  4. Generate all of your random passwords executing ``scripts/pw-token-gen.py --file /etc/opc_deploy/user_secrets.yml``.
  5. Assuming that you have all your networking setup on your host machines move to the ``playbooks/`` directory and execute your desired plays.  IE: ``rpc-ansible setup-everything.yml``


Notes
-----

* If you run the ``bootstrap.sh`` script a wrapper script will be added to your system that wraps the ansible-playbook command to simplify the arguments required to run rpc ansible plays.
* The lxc network is created within the *br-lxc* interface. This supports both NAT networks as well as more traditional networking. If NAT is enabled (default) the IPtables rules will be created along with the interface as a post-up processes. 
* The tool ``lxc-system-manage`` is available on all lxc hosts and can assist in recreating parts of the LXC system whenever its needed.
* Library has an experimental `LXC` module which adds ``lxc:`` support to Ansible. The module within is presently pending in upstream ansible at "https://github.com/ansible/ansible-modules-extras/pull/123"
