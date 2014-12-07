#!/usr/bin/env bash
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

set -o -v -e

GIT_REPO="https://github.com/ansible/ansible"
GIT_RELEASE="${GIT_RELEASE:-v1.8.2}"
WORKING_DIR="/opt/ansible_${GIT_RELEASE}"
GET_PIP_URL="http://mirror.rackspace.com/rackspaceprivatecloud/downloads/get-pip.py"
SSH_DIR="/root/.ssh"

# Export known paths
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

# Create the ssh dir if needed
if [ ! -d "${SSH_DIR}" ];then
    mkdir -p "${SSH_DIR}"
    chmod 700 "${SSH_DIR}"
fi

# Make the system key used for bootstrapping self if needed
if [ ! -f "${SSH_DIR}/id_rsa" ];then
    echo y | ssh-keygen -t rsa -f "${SSH_DIR}/id_rsa" -N ''
    pushd "${SSH_DIR}"
        cat id_rsa.pub | tee -a authorized_keys
    popd
fi

# Install the base packages
(apt-get update && apt-get -y install git python-all python-dev curl) || yum install git python-devel curl

# If the working directory exists remove it
if [ -d "${WORKING_DIR}" ];then
    rm -rf "${WORKING_DIR}"
fi

# Clone down the base ansible source
git clone "${GIT_REPO}" "${WORKING_DIR}"
pushd "${WORKING_DIR}"
    git checkout "${GIT_RELEASE}"
    git submodule update --init --recursive
popd

# Install pip
curl ${GET_PIP_URL} > /opt/get-pip.py
python2 /opt/get-pip.py || python /opt/get-pip.py

# Install requirements if there are any
if [ -f "requirements.txt" ];then
    pip2 install -r requirements.txt || pip install -r requirements.txt
fi

# Install ansible
pip2 install "${WORKING_DIR}" || pip install "${WORKING_DIR}"
