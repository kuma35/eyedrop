# eyedrop

An Android app and command-line tool that tracks eye drop stock and estimates
how many bottles to ask for at your next eye doctor visit.
The user interface and documentation are in Japanese.

| Summary | Stock | Eye drops | Detail |
|---|---|---|---|
| <img src="images/summary.png" width="180" alt="Summary"> | <img src="images/stock.png" width="180" alt="Stock"> | <img src="images/drugs.png" width="180" alt="Eye drops"> | <img src="images/detail.png" width="180" alt="Detail"> |

## Features

- Records prescriptions, opened bottles and stocktaking
- Estimates how many days one bottle lasts from recent usage
- Calculates the bottles needed until the next visit, with the basis of the calculation
- Backup and restore; the Android app works offline with its own data

## Install (Android)

Download `eyedrop.apk` from [Releases](../../releases) and install it
(Android 7.0 or later, arm64-v8a).

Signing certificate: `CN=kuma35`, SHA-256
`97:4A:8A:A3:16:77:C6:CF:66:BA:03:AE:A0:47:88:37:CB:A8:07:05:83:62:6D:FD:34:35:8F:32:19:23:4D:A0`

## Command-line version

Requires Python 3.9 or later (standard library only; tested with 3.9 to 3.13).

```sh
git clone <<this-repo>> eyedrop
cd eyedrop
drugdb/cmd_drugdb.sh help
```

`eyedrop-sample.db` is sample data. Copy it before use, as opening it updates the file.

## Documentation

Detailed documentation (in Japanese) will be available on GitHub Pages.

## License

MIT License. See [LICENSE](LICENSE).

## Disclaimer

This tool only gives an estimate. Always follow your doctor's instructions.
