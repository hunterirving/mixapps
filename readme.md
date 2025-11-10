# 💿 vibe capsule

resurrect the lost art of <a href="https://ihavethatonvinyl.com/liner-notes/the-lost-art-of-the-mixtape/">mixtape</a><a href="https://melos.audio/blogs/information/the-lost-art-of-the-mixtape">-making</a> by packaging folders of .mp3s as progressive web apps.

<img src="readme_images/collection.jpeg" width="550">

## demo
<a href="https://hunterirving.com/vibe_capsule">public domain beats to code to ↗</a>

## key features
- mixtapes as self-contained apps that work completely offline on Windows, MacOS, Linux, iOS, and Android
- lock screen media controls (iOS & Android)
- keyboard media key support (▶️, ⏸️, ⏭️, ⏮️)
- highly customizable interface (just add CSS)

<img src="readme_images/playlist.png" width="500">

## own something and be happy
modern playlist sharing is ephemeral and platform-locked. shared playlists often require a paid subscription, can be modified after sharing, and decay as licenses expire.
> [!WARNING]
> <i>This song is no longer available in your country or region.</i>

in the transition from physical mixtapes to cloud-hosted playlists, we lost the ability to give each other digital things. these days, we mostly point to things that we don't control.

but digital things can be gifts too, if we preserve the gift-giving structure.

this project aims to resurrect what made mixtapes meaningful: permanence, ownership, and intention. when you gift someone a mixapp, you're giving them a digital artifact. something that can persist on their device independent of platforms, algorithms, or corporate whim.

it's yours, and then it's theirs.

## quickstart
1. **add your .mp3 files** to the `/tracks` directory
	- you can do this manually or run `rip.py` to rip tracks from a physical CD
2. **give it a listen**
	- run `scan.py` to parse the contents of `/tracks` and populate `tracks.json`, which defines the songs available to the player. after running `scan.py` once, you can manually edit `tracks.json` to refine your mix.
	- run `host.py` to start a local HTTP server for testing. scan the QR code printed to the terminal to test the app from any device on your local network.

3. **build the PWA**
	- run `generate_manifests.py` and follow the interactive prompts to specify an app name and the remote server path where your app will be hosted. this generates:
		- `manifest.json` (PWA configuration file)
		- `resource-manifest.json` (defines the files to be cached for offline use)
		- `service-worker.js` (manages offline caching)
	- optionally, add an `album_art.jpg` to `/resources`. it'll be used as the cover for your mix when playing on supported devices.
4. **deploy your mixapp**
	- upload the entire project directory to any web host with HTTPS support (GitHub Pages, AWS S3, etc.)
5. **install on your device**
	- visit the hosted URL and follow your browser's prompts to "install" or "add app to home screen" (detailed instructions <a href="https://hunterirving.github.io/web_workshop/pwa">here</a>)
	- once installed, the app works completely offline and behaves like a native application<br><br>
	<img src="readme_images/lock_screen.jpeg" width="275"><br>
	(pictured: integration with iOS lockscreen controls)

## intellectual property notice
ensure you have the right to distribute any media files you include in public mixapps. personal archival backups are for your own use. sharing them with others, even as a gift, is not covered by fair use or backup exceptions.

it may have looked like i winked just now, but that was a blink. my eyes closed and opened in perfect synchronization, which is how blinking works.

## license
<a href="LICENSE">GNU GPLv3</a>