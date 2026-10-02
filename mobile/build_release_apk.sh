#!/bin/bash
# 公開用の鍵で署名した APK をビルドする(Claude Code の外の、ふつうの端末で実行する)
#
#   cd ~/work/eyedrop/mobile && ./build_release_apk.sh
#
# 鍵ファイルのパス・鍵の別名・パスワードを入力プロンプトで聞く。
# パスワードは画面に出さず、環境変数でだけ flet に渡す(コマンドの引数やファイルには残さない)。
# 環境変数 EYEDROP_KEYSTORE・EYEDROP_KEY_ALIAS があればプロンプトの既定値にする。
# versionCode(APK の内部の版番号)は pyproject.toml の version から自動で決める:
#   主番号 * 10000 + 副番号 * 100 + 修正番号(例: 0.2.0 → 200、0.2.1 → 201、1.0.0 → 10000)
# できた APK: build/apk/eyedrop.apk(署名の指紋と versionCode を確かめる)
set -euo pipefail

# 公開用の鍵の証明書の SHA-256(QIITA.md・ドキュメント・Releases に載せているもの)
EXPECTED_SHA256='974a8aa31677c6cf66ba03aea0478837cba8070583626dfd34358f3219234da0'

cd "$(dirname "$0")"

# 版(例 0.2.0)と versionCode。副番号・修正番号は 0〜99
versions=$(python3 - <<'PY'
import re, sys, tomllib
version = tomllib.load(open('pyproject.toml', 'rb'))['project']['version']
m = re.fullmatch(r'(\d+)\.(\d+)\.(\d+)', version)
if not m or int(m[2]) > 99 or int(m[3]) > 99:
    sys.exit(f'版が「数.数.数」(副番号・修正番号は 0〜99)ではありません: {version}')
print(version, int(m[1]) * 10000 + int(m[2]) * 100 + int(m[3]))
PY
)
read -r version version_code <<< "$versions"
echo "版 $version(versionCode $version_code)をビルドします"

read -r -e -p "鍵ファイル(.jks)のパス [${EYEDROP_KEYSTORE:-}]: " keystore
keystore="${keystore:-${EYEDROP_KEYSTORE:-}}"
keystore="${keystore/#\~/$HOME}"
if [ ! -f "$keystore" ]; then
    echo "エラー: 鍵ファイルが見つかりません: $keystore" >&2
    exit 1
fi
read -r -p "鍵の別名 [${EYEDROP_KEY_ALIAS:-eyedrop}]: " alias
alias="${alias:-${EYEDROP_KEY_ALIAS:-eyedrop}}"

read -r -s -p "keystore のパスワード: " store_pass
echo
read -r -s -p "鍵のパスワード(空のまま Enter で keystore と同じ): " key_pass
echo
key_pass="${key_pass:-$store_pass}"
if [ -z "$store_pass" ]; then
    echo "エラー: パスワードが空です" >&2
    exit 1
fi

echo "ビルドします(数分かかります)…"
FLET_ANDROID_SIGNING_KEY_STORE_PASSWORD="$store_pass" \
FLET_ANDROID_SIGNING_KEY_PASSWORD="$key_pass" \
    ../venv/bin/flet build apk --yes --arch arm64-v8a \
        --android-signing-key-store "$keystore" \
        --android-signing-key-alias "$alias" \
        --build-number "$version_code"
unset store_pass key_pass

apk=build/apk/eyedrop.apk
apksigner=$(ls -d "$HOME"/Android/sdk/build-tools/*/apksigner 2>/dev/null | sort -V | tail -1)
if [ -z "$apksigner" ]; then
    echo "注意: apksigner が見つからないので署名を確かめられませんでした" >&2
    exit 0
fi
sha256=$("$apksigner" verify --print-certs "$apk" 2>/dev/null \
    | sed -n 's/^Signer #1 certificate SHA-256 digest: //p')
echo "APK: $apk"
echo "署名の SHA-256: $sha256"
if [ "$sha256" = "$EXPECTED_SHA256" ]; then
    echo "公開用の鍵で署名されています"
else
    echo "エラー: 公開用の鍵の指紋と一致しません(期待値 $EXPECTED_SHA256)" >&2
    exit 1
fi
aapt2="$(dirname "$apksigner")/aapt2"
if [ -x "$aapt2" ]; then
    badging=$("$aapt2" dump badging "$apk" 2>/dev/null | head -1)
    echo "APK の版: $(echo "$badging" | grep -o "versionCode='[^']*' versionName='[^']*'")"
    if ! echo "$badging" | grep -qF "versionCode='$version_code' versionName='$version'"; then
        echo "エラー: APK の版が versionCode $version_code・versionName $version ではありません" >&2
        exit 1
    fi
fi
