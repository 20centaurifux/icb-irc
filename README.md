# Introduction

icb-irc is an experimental [Internet CB Network](http://www.icb.net/) bridge for IRC. It will pass ICB messages through to IRC, and IRC messages through to ICB.

# Running the bridge

At first customize the configuration file ("config.json").

## server

Hostname of your bridge.

	"server":
	{
		"hostname": "localhost"
	}

## bindings

This array contains the network bindings (TCP and TLS over TCP).

	"bindings":
	[
		"tcp://localhost:6667",
		"tcps://localhos:6668t?cert=./runtime/selfsigned.cert&key=./runtime/selfsigned.key"
	]

## icb

ICB server you want to connect to (TLS not implemented yet).

	"icb"
	{
		"endpoint": "tcp://internetcitizens.band:7326"
	}

You need at least Python 3.7 to start the service.

	 python3 ircd/ircd.py --config=./config.json

# Channel modes

Channel modes are read-only over IRC. The ICB group status is translated the following way:

* moderated: +t
* restricted: +ti
* controlled: +tC
* secret: +p
* invisible: +s
* quiet: +q

If a group is controlled (C), only invited users are allowed to speak. The +v user mode isn't supported.

# ICB commands

Write a message to "server" if you want to run ICB commands:

	/msg server help icb
