#
# Copyright (c) SAS Institute Inc.
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


man_files = \
	rmake.1	\
	rmake-server.8 \
	rmake-multinode.1 \
	rmake-multinode.8 \
	rmake-node.8

extra_dist = Makefile

dist_files = $(man_files) $(extra_dist)

all: default-all

install-mkdirs: install-client-mkdirs
	mkdir -p $(DESTDIR)$(mandir)/man8

install-client-mkdirs:
	mkdir -p $(DESTDIR)$(mandir)/man1

install-client: install-client-mkdirs
	$(INSTALL) -m 644 rmake.1 rmake-multinode.1 $(DESTDIR)$(mandir)/man1

install: install-mkdirs install-client
	$(INSTALL) -m 644 rmake-server.8 rmake-multinode.8 rmake-node.8 $(DESTDIR)$(mandir)/man8

dist: default-dist

clean: default-clean

include ../Make.rules
include ../Make.defs
