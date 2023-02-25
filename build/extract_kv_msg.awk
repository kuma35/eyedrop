# -*- coding:utf-8 -*-
{
    if (match($0, /_\(['][^"]+[']\)/, q)) {
	print q[0]
    } else if (match($0, /_\(["][^"]+["]\)/, q)) {
	print q[0]
    } else {
	print "#" $0
    }
}
