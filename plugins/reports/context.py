"""What AndRep reads from Kitebase: records, templates and resources.

Three adapters, the only place that knows both sides:

- KitebaseView: a Kitebase record as templates see it. The columns and
  relations of the mapper, plus the virtual columns of the table, minus the
  secret ones: `[row.password]` on a user is an error in the cell, not the hash.
- LayeredLoader: the templates of the plugins' `andrep/` folders, in
  dependency order, with the installation's `_andrep/` on top. A report's
  variants are every file whose name starts with the report's name.
- PublicResolver: the resources a template may print, named roots only and
  never the network.
"""
import re
from pathlib import Path
from types import MappingProxyType
from typing import Dict, List, Sequence

from andrep import ResourceError, register_view
from andrep.adapters import VALUE
from andrep.adapters.sqlalchemy import SQLAlchemyView
from andrep.resources import DefaultResolver

from kitebase.db import Base
from kitebase.utils import table_definition

TEMPLATES = 'andrep'           # the folder of a plugin holding its templates
INSTALLATION = '_andrep'       # the installation layer, beside config.yaml

# A template is named by its file name, without folders.
_NAME = re.compile(r'^[A-Za-z0-9_][A-Za-z0-9_.-]*$')


class KitebaseView(SQLAlchemyView):
    """The declared fields of a Kitebase record, without its secrets."""

    __slots__ = ()

    _fields: dict = {}   # mapped class -> fields

    @classmethod
    def fields(cls, record):
        model = type(record)
        found = cls._fields.get(model)
        if found is None:
            names = dict(super().fields(record))
            table = table_definition(model)
            if table is not None:
                for col in table.effective_columns:
                    if col.attributes.get('virtual'):
                        names.setdefault(col.name, VALUE)
                for name in table.secret_columns:
                    names.pop(name, None)
            found = cls._fields[model] = MappingProxyType(names)
        return found


register_view(Base, KitebaseView)


class LayeredLoader:
    """Templates by file name, from layers listed lowest first: the last wins."""

    def __init__(self, layers: Sequence[Path]):
        self.layers: List[Path] = [Path(p) for p in layers]

    @staticmethod
    def _check(name: str) -> None:
        if not isinstance(name, str) or not _NAME.match(name) or '..' in name:
            raise ValueError(f"template name {name!r} is not a file name")

    def load(self, name: str) -> dict:
        import json

        self._check(name)
        for layer in reversed(self.layers):
            path = layer / f'{name}.json'
            if path.is_file():
                # No symlink out of the layer: a name stays inside it.
                if not path.resolve().is_relative_to(layer.resolve()):
                    raise ValueError(f"template {name!r} resolves outside {layer}")
                return json.loads(path.read_text(encoding='utf-8'))
        raise FileNotFoundError(f"template {name!r} not found")

    def variants(self, prefixes: Sequence[str]) -> List[str]:
        """The names of the templates starting with one of `prefixes`, sorted."""
        found = set()
        for layer in self.layers:
            if not layer.is_dir():
                continue
            for path in layer.glob('*.json'):
                if path.stem.startswith(tuple(prefixes)) and _NAME.match(path.stem):
                    found.add(path.stem)
        return sorted(found)


class PublicResolver:
    """`root:path` inside the named roots it is given; nothing else.

    No relative paths (the renderer's default reads them from the current
    directory), no URLs: the network is the one way a template could send
    data out.
    """

    def __init__(self, roots: Dict[str, Path]):
        self.roots = dict(roots)
        self._files = DefaultResolver(roots=self.roots, network=False)

    def open(self, ref: str):
        if '://' in ref:
            raise ResourceError('network access is disabled')
        name, sep, _ = ref.partition(':')
        if not sep or name not in self.roots:
            raise ResourceError('not a public resource')
        return self._files.open(ref)


def plugin_layers(pm) -> List[Path]:
    """The `andrep/` folders of the plugins, in dependency order, then `_andrep/`."""
    layers = [pm.plugins[name].plugin_dir / TEMPLATES for name in pm.sorted]
    layers = [p for p in layers if p.is_dir()]
    layers.append(Path(pm.app_root) / INSTALLATION)
    return layers


def public_roots(pm) -> Dict[str, Path]:
    """One root per plugin with templates, named after it: `demo_ui:logo.png`."""
    roots = {}
    for name in pm.sorted:
        folder = pm.plugins[name].plugin_dir / TEMPLATES
        if folder.is_dir():
            roots[name] = folder
    return roots
