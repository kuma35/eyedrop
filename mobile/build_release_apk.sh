#!/bin/bash
# 公開用の鍵で署名した APK をビルドする(Claude Code の外の、ふつうの端末で実行する)
#
#   cd ~/work/eyedrop/mobile && ./build_release_apk.sh
#
# 鍵ファイルのパス・鍵の別名・パスワードを入力プロンプトで聞く。
# パスワードは画面に出さず、環境変数でだけ flet に渡す(コマンドの引数やファイルには残さない)。
# 環境変数 EYEDROP_KEYSTORE・EYEDROP_KEY_ALIAS があればプロンプトの既定値にする。
# できた APK: build/apk/eyedrop.apk(署名の指紋を表示して、公開用の鍵と一致するか確かめる)
set -euo pipefail

# 公開用の鍵の証明書の SHA-256(QIITA.md・ドキュメント・Releases に載せているもの)
EXPECTED_SHA256='974a8aa31677c6cf66ba03aea0478837cba8070583626dfd34358f3219234da0'

cd "$(dirname "$0")"

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
        --android-signing-key-alias "$alias"
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
