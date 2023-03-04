#!/usr/bin/bash
BUILD_DIR=${HOME}/work/eyedrop/build
SRC_DIR=locale
RELEASE_DIR=../locale
MO_FILE=eyedrop.mo

pushd ${BUILD_DIR}

for lang in $(ls ${SRC_DIR})
do
    src_path=locale/${lang}/LC_MESSAGES
    dst_path=${RELEASE_DIR}/${lang}/LC_MESSAGES
    if [ ! -e ${dst_path} ] ; then
	mkdir -p ${dst_path}
    fi
    cp ${src_path}/${MO_FILE} ${dst_path}
done

popd
