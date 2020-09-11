import argparse
import json
import os
import sys
from collections import defaultdict
from functools import lru_cache
from itertools import count
from typing import List, Set

import requests
from packaging.specifiers import SpecifierSet
from packaging.requirements import Requirement
import packaging.version as pv

sess = requests.Session()

parse_requirement = lru_cache(maxsize=None)(Requirement)


def monkeypatch():
    # Hack in some caches to make things faster...
    pv._cmpkey = lru_cache(maxsize=None)(pv._cmpkey)
    pv.parse = lru_cache(maxsize=None)(pv.parse)


def get_pypi_data(name: str, version=None):
    if version:
        cache_file = f"cache/{name.lower()}@{version}.json"
        url = f"https://pypi.org/pypi/{name}/{version}/json"
    else:
        cache_file = f"cache/{name.lower()}.json"
        url = f"https://pypi.org/pypi/{name}/json"
    if os.path.isfile(cache_file):
        with open(cache_file, "r") as f:
            return json.load(f)
    resp = sess.get(url)
    resp.raise_for_status()
    data = resp.json()
    with open(cache_file, "w") as f:
        json.dump(data, f, sort_keys=True, indent=2, ensure_ascii=False)
    return data


class Package:
    def __init__(self, blob):
        self.versions = set()
        self.version_infos = {}
        self.blob = blob
        info = blob["info"]
        self.name = info["name"].lower()
        self.versions = set(blob["releases"].keys())
        self.add_version_info(blob)

    def add_version_info(self, blob):
        info = blob["info"]
        self.version_infos[info["version"]] = info

    def get_best_version(self, constraints: Set[SpecifierSet]):
        if constraints:
            acceptable_versions = [
                version
                for version in self.versions
                if all(version in c for c in constraints if c)
            ]
        else:
            acceptable_versions = self.versions
        if not acceptable_versions:
            raise RuntimeError(f"No {self.name} versions satisfy {constraints}!")
        return max(acceptable_versions, key=pv.parse)

    def get_requirements(self, version) -> List[Requirement]:
        deps = self.version_infos[version].get("requires_dist") or []
        return [parse_requirement(dep) for dep in deps]


class Pypiverse:
    def __init__(self):
        self.packages = {}

    def populate(self, name: str, version=None):
        name = name.lower()
        pkg = self.packages.get(name)
        if not pkg:
            pkg = Package(get_pypi_data(name))
            self.packages[pkg.name] = pkg
        if version and version not in pkg.version_infos:
            pkg.add_version_info(get_pypi_data(name, version))
        return pkg


def tighten_constraints(pypiverse, constraints):
    resolution = {}
    new_constraints = defaultdict(list)
    for package_name, constraint in constraints.items():
        pkg = pypiverse.populate(package_name)
        version = pkg.get_best_version(constraint)
        resolution[package_name] = version
        pypiverse.populate(pkg.name, version)
        for req in pkg.get_requirements(version):
            if req.marker:
                continue  # TODO: support these
            new_constraints[req.name].append(req.specifier)

    return resolution, new_constraints


def pipimi(initial_constraint_strings):
    pypiverse = Pypiverse()
    constraints = defaultdict(set)
    for ics in initial_constraint_strings:
        req = Requirement(ics)
        constraints[req.name].add(req.specifier)

    last_resolution = None
    for round in count(1):
        print(
            f"Round {round}, {len(constraints)} constrained packages", file=sys.stderr
        )
        resolution, new_constraints = tighten_constraints(pypiverse, constraints)
        for name, rset in new_constraints.items():
            constraints[name].update(set(rset))
        if resolution == last_resolution:
            break
        last_resolution = resolution
    return last_resolution, constraints


def main():
    monkeypatch()
    ap = argparse.ArgumentParser()
    ap.add_argument("req", nargs="*")
    ap.add_argument("--show-constraints", action="store_true")
    ap.add_argument("-r", dest="filenames", action="append", default=[])
    args = ap.parse_args()
    initial = list(args.req)
    for filename in args.filenames:
        with open(filename, "r") as f:
            for l in f:
                l = l.strip()
                if l.startswith("#") or not l:
                    continue
                initial.append(l)

    resolution, constraints = pipimi(initial)

    for name, version in sorted(resolution.items()):
        req = f"{name}=={version}"
        if args.show_constraints:
            package_cons = ', '.join(sorted(set(str(c) for c in constraints.get(name))))
            if package_cons:
                print(f"{req}  # {package_cons}")
                continue
        print(req)


if __name__ == "__main__":
    main()
