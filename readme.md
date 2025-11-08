# 💿 vibe capsule

turn a folder of .mp3 files into a progressive web app, resurrecting the lost art of <a href="https://ihavethatonvinyl.com/liner-notes/the-lost-art-of-the-mixtape/">mixtape</a><a href="https://melos.audio/blogs/information/the-lost-art-of-the-mixtape">-making</a>.

<img src="readme_images/collection.jpeg" width="550">

## live demo
<a href="https://hunterirving.com/vibe_capsule">public domain beats to code to ↗</a>

## key features
- playlists as self-contained apps that work completely offline on Windows, MacOS, Linux, iOS, and Android
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

this project aims to resurrect what made mixtapes meaningful: permanence, ownership, and intention. when you gift someone a vibe capsule, you're giving them a digital artifact. something that can persist on their device independent of platforms, algorithms, or corporate whim.

it's **yours** and then it's **theirs**.

## quickstart
1. **add your .mp3 files** to the `/tracks` directory
	- you can do this manually or run `rip.py` to rip tracks from a physical CD
2. **give it a listen**
	- `scan.py` reads the contents of `/tracks` to populate `tracks.json`, which defines the songs that will be available to the player. after running `scan.py` once, you can manually edit `tracks.json` to refine your mix.
	- `host.py` starts a local HTTP server for testing. scan the QR code printed to the terminal to access your playlist from any device on your local network.
3. **build the PWA**
	- in `generate_manifests.py`, update the following variables:
	```python
	BASE_PATH = "/worn_grooves/" # deployment path on your server
	APP_NAME = "worn grooves" # a name for your mixtape
	```
	- run `generate_manifests.py` to create:
		- `manifest.json` (PWA installation requirement)
		- `resource-manifest.json` (defines the files to be cached for offline use)
		- `service-worker.js` (manages the static file cache)
	- optionally, add an `album_art.jpg` to `/resources`. it'll be used as the cover for your mix when playing on supported devices.
4. **deploy your playlist** as a Progressive Web App
	- upload the entire project directory to any web host with HTTPS support (GitHub Pages, AWS S3, etc.)
	- visit your hosted URL and follow your browser's prompts to "install" or "add app to home screen" (detailed instructions <a href="https://hunterirving.github.io/web_workshop/pwa">here</a>)
	- once installed, the app works completely offline and runs like a native application:<br><br>
	<img src="readme_images/lock_screen.jpeg" width="275">

## intellectual property notice
ensure you have the right to distribute any media files you include in public vibe capsules. personal archival backups are for your own use. sharing them with others, even as a gift, is not covered by fair use or backup exceptions.

it may have looked like i winked just now, but i assure you, i did not. that was a blink. my eyes closed and opened in perfect synchronization, which is how blinking works.

## license
<a href="LICENSE">GNU GPLv3</a>