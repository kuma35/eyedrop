#!/bin/sh
# 目薬管理 CLI 版(eyedrop)のインストール・アンインストール
#
#   ./install.sh                  # ~/bin/eyedrop と ~/share/man/man1/eyedrop.1 に入れる
#   PREFIX=~/.local ./install.sh  # ~/.local/bin、~/.local/share/man に入れる
#   ./install.sh --uninstall      # 取り除く(データベースはそのまま)
#
# 入るもの: $PREFIX/bin/eyedrop(起動スクリプト)、$PREFIX/share/eyedrop/drugdb/(本体)、
#           $PREFIX/share/man/man1/eyedrop.1(man ページ)
# データベースの既定は ~/.local/share/eyedrop/eyedrop.db(install.sh は触らない)
set -eu

PREFIX="${PREFIX:-$HOME}"
PYTHON="${PYTHON:-python3}"
SRC="$(cd "$(dirname "$0")" && pwd)"
BIN_DIR="$PREFIX/bin"
LIB_DIR="$PREFIX/share/eyedrop"
MAN_DIR="$PREFIX/share/man/man1"
# 起動スクリプトの目印(アンインストール時に他のファイルを消さないため)
MARK='# eyedrop launcher (install.sh)'

uninstall() {
    if [ -f "$BIN_DIR/eyedrop" ]; then
        if grep -qF "$MARK" "$BIN_DIR/eyedrop"; then
            rm -f "$BIN_DIR/eyedrop"
            echo "削除: $BIN_DIR/eyedrop"
        else
            echo "注意: $BIN_DIR/eyedrop は install.sh で入れたものではないので残します" >&2
        fi
    fi
    if [ -d "$LIB_DIR" ]; then
        rm -rf "$LIB_DIR"
        echo "削除: $LIB_DIR"
    fi
    if [ -f "$MAN_DIR/eyedrop.1" ]; then
        rm -f "$MAN_DIR/eyedrop.1"
        echo "削除: $MAN_DIR/eyedrop.1"
    fi
    echo "データベース(既定 ~/.local/share/eyedrop/eyedrop.db)は残してあります"
}

install() {
    if ! "$PYTHON" -c 'import sys; sys.exit(sys.version_info < (3, 9))' 2>/dev/null; then
        echo "エラー: Python 3.9 以上が必要です($PYTHON)" >&2
        exit 1
    fi
    if [ -f "$BIN_DIR/eyedrop" ] && ! grep -qF "$MARK" "$BIN_DIR/eyedrop"; then
        echo "エラー: $BIN_DIR/eyedrop が既にあります(install.sh で入れたものではありません)" >&2
        exit 1
    fi
    mkdir -p "$BIN_DIR" "$LIB_DIR" "$MAN_DIR"

    # 本体(Python ファイルだけ)。古いファイルが残らないよう入れ直す
    rm -rf "$LIB_DIR/drugdb"
    mkdir -p "$LIB_DIR/drugdb"
    cp "$SRC"/drugdb/*.py "$LIB_DIR/drugdb/"

    cat > "$BIN_DIR/eyedrop" <<EOF
#!/bin/sh
$MARK
PYTHONPATH="$LIB_DIR\${PYTHONPATH:+:\$PYTHONPATH}" exec "$PYTHON" -m drugdb "\$@"
EOF
    chmod 755 "$BIN_DIR/eyedrop"

    cp "$SRC/man/eyedrop.1" "$MAN_DIR/eyedrop.1"
    chmod 644 "$MAN_DIR/eyedrop.1"

    echo "インストールしました: $("$BIN_DIR/eyedrop" --version)"
    echo "  コマンド: $BIN_DIR/eyedrop"
    echo "  本体:     $LIB_DIR/drugdb/"
    echo "  man:      $MAN_DIR/eyedrop.1"
    case ":$PATH:" in
        *":$BIN_DIR:"*) ;;
        *) echo "注意: $BIN_DIR が PATH に入っていません。PATH に追加するか、ログインし直してください" ;;
    esac
}

case "${1:-}" in
    --uninstall) uninstall ;;
    '') install ;;
    *) echo "使い方: $0 [--uninstall]   (入れる場所は環境変数 PREFIX。既定 \$HOME)" >&2
       exit 2 ;;
esac
