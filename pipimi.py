import argparse
import json
import os
import sys
from collections import defaultdict
from distutils.version import LooseVersion
from itertools import count
from typing import List, Set

import requests
from packaging.specifiers import SpecifierSet
from packaging.requirements import Requirement

sess = requests.Session()


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
                if all(version in c for c in constraints)
            ]
        else:
            acceptable_versions = self.versions
        return max(acceptable_versions, key=LooseVersion)

    def get_requirements(self, version) -> List[Requirement]:
        deps = self.version_infos[version].get("requires_dist") or []
        return [Requirement(dep) for dep in deps]


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
    ap = argparse.ArgumentParser()
    ap.add_argument("req", nargs="*")
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
        print(f"{name}=={version}")


if __name__ == "__main__":
    main()
