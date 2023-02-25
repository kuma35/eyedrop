# -*- coding:utf-8 -*-
/_\(/ {
    if (match($0, /_\(['][^"]+[']\)/, q)) {
	print q[0]
    } else if (match($0, /_\(["][^"]+["]\)/, q)) {
	print q[0]
    }
}
