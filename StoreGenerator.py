import sys, os, io

import yaml
import collections
import contextlib

def main(_, cfname=None, installdir=None):
	root = os.path.dirname(os.path.abspath(__file__))
	if cfname is None:
		cfname = os.path.join(root, f'{os.path.splitext(os.path.basename(__file__))[0]}.yaml')
	if installdir is None:
		installdir = root
	# Read config file
	with io.open(cfname, 'r', encoding='utf-8') as file:
		config = yaml.safe_load(file)
	# Create stores
	for name, store in config.items():
		print(f'Generating >{name}< store')
		Store(name, installdir, store).export(installdir)
	print(f'All done!')

# Define '!append' and '!prepend' tags in Yaml
TaggedValue = collections.namedtuple('TaggedValue', 'value')
class Append(TaggedValue): pass
class AppendOnce(TaggedValue): pass
class AppendFrom(TaggedValue): pass
class Prepend(TaggedValue): pass
class PrependOnce(TaggedValue): pass
class PrependFrom(TaggedValue): pass
class Remove(TaggedValue): pass

def yaml_create_append(loader, node):
	return Append(node.value)
def yaml_create_append_once(loader, node):
	return AppendOnce(node.value)
def yaml_create_append_from(loader, node):
	return AppendFrom(node.value)
def yaml_create_prepend(loader, node):
	return Prepend(node.value)
def yaml_create_prepend_once(loader, node):
	return PrependOnce(node.value)
def yaml_create_prepend_from(loader, node):
	return PrependFrom(node.value)
def yaml_create_remove(loader, node):
	return Remove(node.value)

yaml.SafeLoader.add_constructor('!append', yaml_create_append)
yaml.SafeLoader.add_constructor('!append-once', yaml_create_append_once)
yaml.SafeLoader.add_constructor('!append-from', yaml_create_append_from)
yaml.SafeLoader.add_constructor('!prepend', yaml_create_prepend)
yaml.SafeLoader.add_constructor('!prepend-once', yaml_create_prepend_once)
yaml.SafeLoader.add_constructor('!prepend-from', yaml_create_prepend_from)
yaml.SafeLoader.add_constructor('!remove', yaml_create_remove)

# Try to hack PyYaml to allow multiple anchors with the same name. This falls under undefined behaviour and may stop working at some point
with contextlib.suppress(Exception):
	def peek_event_override(self, previous=yaml.parser.Parser.peek_event):
		event = previous(self)
		if event.anchor is not None:
			with contextlib.suppress(KeyError):
				del self.anchors[event.anchor]
		return event
	yaml.parser.Parser.peek_event = peek_event_override

class Util:
	# List based get
	def lget(obj, list, default=None):
		try:
			for index in list:
				obj = obj[index]
			return obj
		except (KeyError, ValueError, IndexError):
			return default

	# Remove item
	def remove(list, item):
		try:
			list.remove(item)
			return True
		except ValueError:
			return False

	# Turns a string into a quoted string literal
	@staticmethod
	def enquote(s):
		return '"{}"'.format(s.replace('\\', '\\\\').replace('"', '\\"'))

	@staticmethod
	def dequote(s):
		if len(s) > 2 and (s[0], s[-1]) == ('"', '"'):
			return s[1:-1].replace('\\"', '"').replace('\\\\', '\\')
		return s

	# Matches a value to a string pattern with wildcards (*)
	@staticmethod
	def match(value, pattern):
		pattern = str.split(pattern, '*')	# Force str type
		# No wildcards
		if len(pattern) == 1:
			return value == pattern[0]
		# Match start and end
		start, end = len(pattern[0]), len(value) - len(pattern[-1])
		if start > end or not value.startswith(pattern[0]) or not value.endswith(pattern[-1]):
			return False
		elif len(pattern) == 2:
			return True
		# Match middle parts
		pattern.pop()
		matches, forward = [(0, start)], True
		while 0 < len(matches) < len(pattern):
			i = len(matches) - 1
			if forward:
				# Forward mode, match next pattern
				pos, size = str.find(value, pattern[i + 1], matches[i][1], end), len(pattern[i + 1])
				if pos >= 0:
					matches.append((pos, pos + size))
				else:
					forward = False
			else:
				# Reverse mode, find new match for current pattern
				pos, size = str.find(value, pattern[i], matches[i][0] + 1, end), len(pattern[i])
				if pos >= 0:
					matches[i], forward = (pos, pos + size), True
				else:
					matches.pop()
		# If all parts were eventually match, its a success
		return bool(matches)

	@staticmethod
	def lmatch(value, anyof, allof=(), noneof=(), *, match=match):
		if anyof:
			for pattern in anyof:
				if match(value, pattern):
					break
			else:
				return False
		for pattern in allof:
			if not match(value, pattern):
				return False
		for pattern in noneof:
			if match(value, pattern):
				return False
		return True

	@staticmethod
	def tagsplit(values, tags={'ANY', 'ALL', 'NOT'}, default='ANY'):
		result = {k : [] for k in tags}
		for value in values:
			try:
				tag, rest = value.split(':', 1)
				if tag in tags:
					result[tag].append(rest)
				else:
					result[default].append(value)
			except ValueError:
				result[default].append(value)
		return result

	@staticmethod
	def findfiles(root, anyof, allof=(), noneof=()):
		result = set()
		# Handle the edge case with only ALL patterns
		if not anyof:
			if not allof:
				return result
			anyof, allof = [allof[0]], allof[1:]
		# Process ANY patterns
		for pattern in anyof:
			pattern = os.path.join(root, pattern).replace('\\', '/')
			# Match case-insensitively, but walk the real path (filesystems may be case sensitive)
			lp = pattern.lower()
			# Process wildcards
			pos = lp.find('*')
			if pos < 0:
				# No wildcards, ALL tag ignored (as it doesn't make any sense)
				result.add(pattern)
			else:
				# Get prefix (after the first '/')
				prefix = lp[:pos]
				prefix = lp[:lp.rfind('/') + 1]
				# Walk the directory using the original case of the path
				oprefix = pattern[:len(prefix)]
				for base, dirs, files in os.walk(oprefix):
					for file in files:
						fullname = os.path.join(base, file).replace('\\', '/')
						if Util.match(fullname.lower(), lp):
							result.add(fullname)
		# Process ALL patterns
		allof = [os.path.join(root, pattern).replace('\\', '/').lower() for pattern in allof]
		for pattern in allof:
			result -= set(path for path in result if not Util.match(path.lower(), pattern))
		# Process NOT patterns
		noneof = [os.path.join(root, pattern).replace('\\', '/').lower() for pattern in noneof]
		for pattern in noneof:
			result -= set(path for path in result if Util.match(path.lower(), pattern))
		return result

# Simulates a Tweak Database for TweakXL, for to recognize item types better
class TweakXLSimulator:

	def __init__(self):
		self.db = {}

	def load(self, text, filename='<unknown>'):
		# Parse yaml
		try:
			data = yaml.safe_load(text)
		except Exception as e:
			data = {}
			print(f'Error: Failed to load file: {filename}. Error" {e}', file=sys.stderr)

		# Apply definitions (expanding TweakXL template tweaks)
		if data is not None:
			for k, v in self.expand(data).items():
				self.define(self.db, k, v)
		else:
			print(f'Warning: Empty data loaded from file: {filename}', file=sys.stderr)

	def loadf(self, file):
		# Handle filename
		if isinstance(file, str):
			with io.open(file, 'r', encoding='utf-8') as f:
				return self.load(f.read(), file)
		# Handle file like object
		self.load(file.read())

	# Expand TweakXL template tweaks: a tweak with '$instances' is duplicated once per
	# instance, substituting ${var} placeholders in the name and in all string values
	def expand(self, data):
		result = {}
		for k, v in data.items():
			if isinstance(v, dict) and v.get('$instances'):
				for inst in v['$instances']:
					body = {k2 : v2 for k2, v2 in v.items() if k2 != '$instances'}
					result[self.subst(k, inst)] = self.subst(body, inst)
			else:
				result[k] = v
		return result

	# Substitute ${var} placeholders in a value using an instance mapping
	@staticmethod
	def subst(obj, inst):
		if isinstance(obj, str):
			for key, value in inst.items():
				obj = obj.replace('${%s}' % key, str(value))
			return obj
		if isinstance(obj, dict):
			return {k : TweakXLSimulator.subst(v, inst) for k, v in obj.items()}
		if isinstance(obj, list):
			return [TweakXLSimulator.subst(x, inst) for x in obj]
		return obj

	def get(self, base, attr, default=None):
		for part in attr.split('.'):
			try:
				base = base[part]
			except (KeyError, IndexError):
				return default
		return base

	def copy(self, obj):
		# Deepcopy object
		if isinstance(obj, dict):
			return {k : self.copy(v) for k, v in obj.items()}
		elif isinstance(obj, (list, tuple)):
			return [self.copy(x) for x in obj]
		else:
			return obj

	def items(self, base=None):
		if base is None:
			base = self.db
		stack = [((), base)]
		while stack:
			path, item = stack.pop()
			yield '.'.join(path), item
			if isinstance(item, dict):
				stack += [((*path, k), v) for k, v in item.items()]

	def define(self, base, attr, value, decode=True):
		# Resolve all but the last attribute in the chain
		if not isinstance(attr, str):
			attr = str(attr)
		attr = attr.split('.')
		for part in attr[:-1]:
			base, prev = base.get(part), base
			if base is None:
				prev[part] = base = {}
		attr = attr[-1]
		# Assign value
		if isinstance(value, dict):
			base, prev = base.get(attr), base
			basename = value.get('$base')
			if basename is not None:
				template = self.get(self.db, basename)
				if template is not None:
					prev[attr] = base = self.copy(template)
			if not isinstance(base, dict):
				prev[attr] = base = {}
			for k, v in value.items():
				if k != '$base':
					self.define(base, k, v)
			if basename:
				base['$base'] = [basename]
				if template:
					base['$base'] += template.get('$base', [])

		elif isinstance(value, (list, tuple)):
			prepend, append, replace = [], [], [item for item in value if not isinstance(item, TaggedValue)]
			if not replace:
				replace = list(base.get(attr, []))
			for item in value:
				if isinstance(item, Append):
					append.append(self.decode(item.value))
				elif isinstance(item, AppendOnce):
					value = self.decode(item.value)
					if all(value not in part for part in [prepend, append, replace]):
						append.append(value)
				elif isinstance(item, AppendFrom):
					source = self.get(self.db, item.value)
					if isinstance(source, (list, tuple)):
						append.extend(source)
				elif isinstance(item, Prepend):
					prepend.append(self.decode(item.value))
				elif isinstance(item, PrependOnce):
					value = self.decode(item.value)
					if all(value not in part for part in [prepend, append, replace]):
						prepend.append(value)
				elif isinstance(item, PrependFrom):
					source = self.get(self.db, item.value)
					if isinstance(source, (list, tuple)):
						prepend.extend(source)
				elif isinstance(item, Remove):
					item = self.decode(item.value)
					Util.remove(prepend, item) or Util.remove(replace, item) or Util.remove(append, item)
			base[attr] = prepend + replace + append

		elif decode:
			base[attr] = self.decode(value)
		else:
			base[attr] = value

	@staticmethod
	def match(name, obj, filter):
		field, filter = filter.split(':', 1)
		if field == '$name':
			if Util.match(name, filter):
				return True
		else:
			value = obj.get(field)
			if isinstance(value, (int, str)):
				if Util.match(str(value), filter):
					return True
			elif isinstance(value, (list, tuple)):
				for item in value:
					if Util.match(str(item), filter):
						return True
		return False

	@staticmethod
	def lmatch(name, obj, anyof, allof=(), noneof=()):
		def match(value, filter):
			return TweakXLSimulator.match(*value, filter)
		return Util.lmatch((name, obj), anyof, allof, noneof, match=match)

	@staticmethod
	def decode(value, CName=True, CResource=True, TweakDBID=True, LocKey=True):
		if isinstance(value, str):
			if CName:
				if value.startswith('n"') and value.endswith('"'):
					return Util.dequote(value[1:])
				elif value.startswith('CName(') and value.endswith(')'):
					return Util.dequote(value[6:].strip())
			if CResource:
				if value.startswith('r"') and value.endswith('"'):
					return Util.dequote(value[1:])
				elif value.startswith('ResRef(') and value.endswith(')'):
					return Util.dequote(value[7:].strip())
			if TweakDBID:
				if value.startswith('t"') and value.endswith('"'):
					return Util.dequote(value[1:])
				elif value.startswith('TweakDBID(') and value.endswith(')'):
					return Util.dequote(value[10:].strip())
			if LocKey:
				if value.startswith('l"') and value.endswith('"'):
					return Util.dequote(value[1:])
				if value.startswith('LocKey#'):
					return value[7:]
				if value.startswith('LocKey(') and value.endswith(')'):
					return Util.dequote(value[7:].strip())
			if value == 'None':
				return None
		return value

class Store:

	Template = '\n'.join([
		'// AUTOMATICALLY GENERATED CODE',
		'@addMethod(gameuiInGameMenuGameController)',
		'protected cb func Register{id}Store(event: ref<VirtualShopRegistration>) -> Bool {{',
		'  event.AddStore(',
		'    n"{id}",',
		'    {name},',
		'    [{items}],',
		'    [{prices}],',
		'    r{atlas},',
		'    n{icon},',
		'    [{qualities}],',
		'    [{supplies}]',
		'  );',
		'}}'
	])

	QualityToIndex = {
		'Quality.Common' : 0,
		'Quality.Uncommon' : 1,
		'Quality.Rare' : 2,
		'Quality.Epic' : 3,
		'Quality.Legendary' : 4,
		'Common' : 0,
		'Uncommon' : 1,
		'Rare' : 2,
		'Epic' : 3,
		'Legendary' : 4,
		None : 0
	}

	IndexToQuality = {
		0: 'Common',
		1: 'Uncommon',
		2: 'Rare',
		3: 'Epic',
		4: 'Legendary',
	}

	# All items are always sold at this price, iconic or not
	Price = 1

	def __init__(self, name, root, config):
		self.name = name
		self.root = root
		self.config = config
		self.store = None

	def build(self):
		# Find source files
		sources = Util.tagsplit(self.config.get('sources', ()))
		files = sorted(Util.findfiles(self.root, sources['ANY'], sources['ALL'], sources['NOT']))
		# Load source files into TweakXL simulator
		self.tweakxl = TweakXLSimulator()
		for file in files:
			self.tweakxl.loadf(file)
		# Build the store
		self.store = {
			'id' : self.config.get('id', self.makeid(self.name)),
			'name' : self.name,
			'atlas' : self.config['icon'][0],
			'icon' : self.config['icon'][1],
			'items' : [],
			'prices' : [],
			'qualities' : [],
			'supplies' : [],
		}

		# Load parameters
		filters = Util.tagsplit(self.config.get('filters', ()))
		blacklist = set(self.config.get('blacklist', []))
		supply_list = Util.lget(self.config, ['supply', 'categories'], {})
		supply_qualities = Util.lget(self.config, ['supply', 'qualities'], ['Default'])
		iconic_supply = Util.lget(self.config, ['supply', 'iconic'])
		default_supply = Util.lget(self.config, ['supply', 'default'], [1, 1, 1, 1, 1])

		# Process TweakXL database
		for k, v in self.tweakxl.items():
			# Keep only full objects
			if not k or not isinstance(v, dict):
				continue
			if (v.get('$type') or v.get('$base')) is None:
				continue
			# Apply blacklist
			if k in blacklist:
				continue
			# Apply filters
			if not self.tweakxl.lmatch(k, v, filters['ANY'], filters['ALL'], filters['NOT']):
				continue

			# Get attributes
			iconic = ('Quality.IconicItem' in v.get('statModifiers', []))
			base_quality = self.QualityToIndex.get(v.get('quality'), 0)
			# Gather qualities
			quality_set = set()
			for quality in supply_qualities:
				if quality in ('Default', None):
					quality_set.add(base_quality)
				else:
					quality = self.QualityToIndex.get(quality)
					if quality is not None:
						quality_set.add(quality)
			if not quality_set:
				quality_set.add(0) # If all else fails add a common quality

			# Create items
			for quality in sorted(quality_set):
				# Calculate supply
				supply = default_supply[quality]
				for category, entry in supply_list.items():
					if self.tweakxl.match(k, v, category):
						supply = entry[quality]
						break
				if iconic and iconic_supply is not None:
					supply = iconic_supply[quality]
				# Add item to store
				self.store['items'].append(k)
				self.store['prices'].append(self.Price)
				self.store['qualities'].append(self.IndexToQuality[quality])
				self.store['supplies'].append(supply)

	def export(self, outdir):
		# Build store when needed
		if self.store is None:
			self.build()
		# Convert arrays to strings
		data = {
			'id' : self.store['id'],
			'name' : Util.enquote(self.store['name']),
			'atlas' : Util.enquote(self.store['atlas']),
			'icon' : Util.enquote(self.store['icon']),
			'items' : ', '.join(Util.enquote(x) for x in self.store['items']),
			'prices' : ', '.join(str(x) for x in self.store['prices']),
			'qualities' : ', '.join(Util.enquote(x) for x in self.store['qualities']),
			'supplies' : ', '.join(str(x) for x in self.store['supplies']),
		}
		# Export store to file
		ofname = os.path.join(outdir, self.config['filename'])
		with io.open(ofname, 'w', encoding='utf-8') as file:
			file.write(self.Template.format(**data))

	@staticmethod
	def makeid(text, charset = set('ABCDEFGHIJKLMNOPQRSTUVWXYZ_')):
		return ''.join(char for char in text.upper() if char in charset)

if __name__ == '__main__':
	main(*sys.argv)