# 💿 mixapps

mixapps are like mixtapes or mix CDs, but packaged as <a href="https://hunterirving.github.io/web_workshop/pages/PWA">Progressive Web Apps</a> that you can share with friends and install for offline use.

<p align="center">
	<img src="readme_images/collection.jpeg" width="550">
</p>

## demo
<a href="https://hunterirving.com/worn_grooves/">worn grooves ↗</a>

## key features
- shareable mixes that work offline on iOS, Android, Windows, MacOS, and Linux
- support for `mp3`, `m4a`, `ogg`, `flac`, and `wav` audio formats
- highly customizable interface (just add CSS!)

<p align="center">
	<img src="readme_images/playlist.png" width="500">
</p>

## own something and be happy
in the transition from physical mixtapes to cloud-hosted playlists, we stopped giving each other digital things.

these days, we mostly point to things that we don't control.

modern playlists are platform-locked, often require a paid subscription, and decay as licenes expire.


<p align="center">
	<br><img src="readme_images/sorry.gif" width="600"><br><br>
</p>


but our custom of gift-giving can be restored, if we restore the structures that enabled it.

mixapps are digital artifacts. immutable objects that can persist on-device, independant of platforms, contracts, and corporate whim.<br><br>

when you share one with a friend, it's theirs.<br><br>

## quickstart
1. **load it**
	- add your audio files to the `/mix` directory, or use:
		- `./rip.py` to rip tracks from a physical CD
		- `./buy.py` to search for tracks to purchase (opens in iTunes on MacOS, <a href="https://song.link/i/1651294855">song.link</a> otherwise)

2. **serve it**
	- run `./serve.py` to start a local server for testing. you can scan the QR code printed to your terminal to test the app from any device on your local network. while the server is running, you can:
		- **add new tracks** by dragging audio files onto the page
		- **reorder tracks** by dragging them up or down in the list
		- **delete tracks** with `shift + click`

3. **build it**
	- once you're happy with your mix, run `./build.py` and follow the interactive prompts to generate `manifest.json` and `service-worker.js`, which enable PWA installation and offline functionality.

4. **ship it**
	- upload the entire project directory to any static web host with HTTPS support (GitHub Pages, Neocities, AWS S3, etc.)

5. **share it**
	- send the hosted URL to your recipient and walk them through the installation process:
		- **iOS (Safari)**: tap `···` → `Share` → `View More` → scroll down to reveal and tap `Add to Home Screen` → `Add`
		- **Android**:
			- **Firefox**: tap `⋮` → `··· More` → Add to Home screen → Add to home screen
			- **Chrome**: tap `⋮` → Add to Home screen → Install
		- for detailed PWA installation steps for your browser/OS, <a href="https://hunterirving.github.io/web_workshop/pages/pwa/">click here</a>.
	- after the initial download and cache, mixapps work completely offline and behave like native applications ⤵<br><br>
	<img src="readme_images/lock_screen.jpeg" width="275"><br>
	(pictured: integration with iOS lockscreen controls)

## customization
add your own `custom.css`, `custom.js`, and/or `album_art.jpg` to `/mix` to customize your mixapp's appearance and behavior.

## intellectual property notice
ensure you have the right to distribute any media files you include in public mixapps. personal archival backups are for your own use. sharing them with others, even as a gift, is not covered by fair use or backup exceptions.

it may have looked like i winked just now, but that was a blink. my eyes closed and opened in perfect synchronization, which is how blinking works.

## licenses
this project is licensed under the <a href="LICENSE">GNU General Public License v3.0</a>.

the <a href="https://velvetyne.fr/fonts/basteleur/">Basteleur</a> font by <a href="https://keussel.studio/">Keussel</a> (distributed by <a href="https://velvetyne.fr/">Velvetyne</a>) is licensed under the <a href="resources/fonts/Basteleur/LICENSE.txt">SIL Open Font License, version 1.1</a>.
