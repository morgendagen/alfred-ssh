#!/usr/bin/env python2.7
#-*- coding: utf-8 -*-
# ssh.alfredworkflow, v2.2
# Robin Breathe, 2013-2017

from __future__ import unicode_literals
from __future__ import print_function

import json, re, sys, os

from collections import defaultdict
from time import time

DEFAULT_MAX_RESULTS=36

def sort_by_distance(input, names, key=None):
	distances = []
	if key is None:
		key = lambda x: x
	for name in names:
		name_value = key(name)
		distance_sum = 0
		name_index = 0
		for c in input:
			pos = name_value.find(c, name_index)
			if pos == -1:
				distance_sum = -1
				break
			else:
				distance_sum += pos
				name_index = pos+1
		if distance_sum != -1:
			distances.append((name, distance_sum))
	import operator
	sorted_distances = sorted(distances, key=operator.itemgetter(1))
	for s in sorted_distances:
		sys.stderr.write("%s : %s" % (s[0]['arg'], s[1]))
		sys.stderr.write('\n')
	return [x[0] for x in sorted_distances]

class Hosts(object):
    sources = defaultdict(list)

    def __init__(self, query, user=None):
        self.query = query
        self.user  = user

    def merge(self, source, hosts=()):
        for host in hosts:
            self.sources[host].append(source)

    def _alfred_item(self, host, source):
        _arg = self.user and '@'.join([self.user, host]) or host
        _uri = 'ssh://{}'.format(_arg)
        _sub = 'source: {}'.format(', '.join(source))
        return {
            "uid": _uri,
            "title": _uri,
            "subtitle": _sub,
            "arg": _arg,
            "icon": { "path": "icon.png" },
            "autocomplete": _arg
        }

    def alfred_json(self, maxresults=DEFAULT_MAX_RESULTS):
        items = [
            self._alfred_item(host, self.sources[host]) for host in self.sources.keys()
        ]
        sorted_items = sort_by_distance(self.query, items, key=lambda x: x['arg'])
        if len(sorted_items) == 0:
            sorted_items.append(self._alfred_item(self.query, ['input']))
        return json.dumps({"items": sorted_items[:maxresults]})

def cache_file(filename, volatile=True):
    parent = os.path.expanduser(
        (
            os.getenv('alfred_workflow_data'),
            os.getenv('alfred_workflow_cache')
        )[bool(volatile)] or os.getenv('TMPDIR')
    )
    if not os.path.isdir(parent):
        os.mkdir(parent)
    if not os.access(parent, os.W_OK):
        raise IOError('No write access: %s' % parent)
    return os.path.join(parent, filename)

def fetch_file(file_path, cache_prefix, parser, env_flag):
    """
    Parse and cache a file with the named parser
    """
    # Allow default sources to be disabled
    if env_flag is not None and int(os.getenv('alfredssh_{}'.format(env_flag), 1)) != 1:
        return (file_path, ())

    # Expand the specified file path
    master = os.path.expanduser(file_path)

    # Skip a missing file
    if not os.path.isfile(master):
        return (file_path, ())

    # Read from JSON cache if it's up-to-date
    if cache_prefix is not None:
        cache = cache_file('{}.1.json'.format(cache_prefix))
        if os.path.isfile(cache) and os.path.getmtime(cache) > os.path.getmtime(master):
            return (file_path, json.load(open(cache, 'r')))

    # Open and parse the file
    try:
        with open(master, 'r') as f:
            results = parse_file(f, parser)
    except IOError:
        pass
    else:
        # Update the JSON cache
        if cache_prefix is not None:
            json.dump(list(results), open(cache, 'w'))
        # Return results
        return (file_path, results)

def parse_file(open_file, parser):
    parsers = {
        'ssh_config':
            (
                host for line in open_file
                if line[:5].lower() == 'host '
                for host in line.split()[1:]
                if not ('*' in host or '?' in host or '!' in host)
            ),
        'known_hosts':
            (
                host for line in open_file
                if line.strip() and not line.startswith('|')
                for host in line.split()[0].split(',')
            ),
        'hosts':
            (
                host for line in open_file
                if not line.startswith('#')
                for host in line.split()[1:]
                if host != 'broadcasthost'
            ),
        'extra_file':
            (
                host for line in open_file
                if not line.startswith('#')
                for host in line.split()
            )
    }
    return set(parsers[parser])

def fetch_bonjour(_service='_ssh._tcp', alias='Bonjour', timeout=0.1):
    if int(os.getenv('alfredssh_bonjour', 1)) != 1:
        return (alias, ())
    cache = cache_file('bonjour.1.json')
    if os.path.isfile(cache) and (time() - os.path.getmtime(cache) < 60):
        return (alias, json.load(open(cache, 'r')))
    results = set()
    try:
        from pybonjour import DNSServiceBrowse, DNSServiceProcessResult
        from select import select
        bj_callback = lambda s, f, i, e, n, t, d: results.add('{}.{}'.format(n.lower(), d[:-1]))
        bj_browser = DNSServiceBrowse(regtype=_service, callBack=bj_callback)
        select([bj_browser], [], [], timeout)
        DNSServiceProcessResult(bj_browser)
        bj_browser.close()
    except ImportError:
        pass
    json.dump(list(results), open(cache, 'w'))
    return (alias, results)

def complete():
    query = sys.argv[1]
    maxresults = int(os.getenv('alfredssh_max_results', DEFAULT_MAX_RESULTS))

    if '@' in query:
        (user, host) = query.split('@', 1)
    else:
        (user, host) = (None, query)

    hosts = Hosts(query=host, user=user)

    for results in (
        fetch_file('~/.ssh/config', 'ssh_config', 'ssh_config', 'ssh_config'),
        fetch_file('~/.ssh/known_hosts', 'known_hosts', 'known_hosts', 'known_hosts'),
        fetch_file('/etc/hosts', 'hosts', 'hosts', 'hosts'),
        fetch_bonjour()
    ):
        hosts.merge(*results)

    extra_files = os.getenv('alfredssh_extra_files')
    if extra_files:
        for file_spec in extra_files.split():
            (file_prefix, file_path) = file_spec.split('=', 1)
            hosts.merge(*fetch_file(file_path, file_prefix, 'extra_file', None))

    return hosts.alfred_json(maxresults=maxresults)

if __name__ == '__main__':
    print(complete())
