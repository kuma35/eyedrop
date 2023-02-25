from pathlib import PurePath, Path

localedir=PurePath(__file__).parent / 'locales'
p = Path(localedir)
print(localedir)
print(p.exists())
