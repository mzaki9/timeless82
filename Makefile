CC=gcc
CFLAGS=-O2 -Wall -Wextra
LIBS=-lhid -lsetupapi

all: timeless82.exe

timeless82.exe: timeless82.c
	$(CC) $(CFLAGS) -o $@ $< $(LIBS)

clean:
	del timeless82.exe
