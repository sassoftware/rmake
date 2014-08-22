/*
 * Copyright (c) SAS Institute Inc.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

#ifndef _COMPAT_H
#define _COMPAT_H

/* Copied clone flags for old userspace-kernel-headers */
#ifndef CLONE_NEWPID
# define CLONE_NEWUTS    0x04000000 /* New utsname group? */
# define CLONE_NEWIPC    0x08000000 /* New ipcs */
# define CLONE_NEWUSER   0x10000000 /* New user namespace */
# define CLONE_NEWPID    0x20000000 /* New pid namespace */
# define CLONE_NEWNET    0x40000000 /* New network namespace */
#endif

#ifndef MAP_STACK
/* This flag is advisory anyway, so if it's not defined by libc then it's a
 * no-op. */
# define MAP_STACK      0
#endif

#endif
