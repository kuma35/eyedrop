#!/usr/bin/bash
PROJECT_DIR=${HOME}/work/eyedrop
BUILD_DIR=build
RELEASE_DIR=../locale
MO_FILE=eyedrop.mo

pushd ${PROJECT_DIR}/${BUILD_DIR}

for lang in $(ls locale)
do
    src_path=locale/${lang}/LC_MESSAGES
    dst_path=${RELEASE_DIR}/${lang}/LC_MESSAGES
    if [ ! -e ${dst_path} ] ; then
	mkdir -p ${dst_path}
    fi
    cp ${src_path}/${MO_FILE} ${dst_path}
done

popd
