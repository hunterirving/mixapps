# 💿 mixapps

mixapps are like mixtapes or mix CDs, but packaged as <a href="https://hunterirving.github.io/web_workshop/pages/pwa">Progressive Web Apps</a> that you can install for offline use.

<p align="center">
	<img src="readme_images/collection.jpeg" width="550">
</p>

## demo
<p align="center">
<a href="https://hunterirving.com/worn_grooves/">worn grooves ↗</a>
<br>(public domain recordings)
</p>

## key features
- installable mixes that work offline on iOS, Android, Windows, MacOS, and Linux
- support for `mp3`, `m4a`, `ogg`, `flac`, and `wav` audio formats
- highly customizable interface (just add CSS!)

<p align="center">
	<img src="readme_images/playlist.png" width="500">
</p>

## own something and be happy

modern playlists are platform-locked, often require a paid subscription, and decay as licenses expire.

these days, we mostly point to things that we don't control.

<p align="center">
	<br><img src="readme_images/sorry.gif" width="600"><br><br>
</p>

<hr><br>

mixapps are digital artifacts. immutable objects that can persist on-device, independent of platforms, contracts, and corporate whim.<br><br>

once you install one, it's yours.<br><br>

> [!IMPORTANT]
> mixapps make it easy to host audio on the public internet. hosting content you don't have the right to distribute is copyright infringement, even when shared privately with a friend or framed as a gift. fair use and backup exceptions cover personal copies, not public hosting.
>
> before uploading, ensure you have the right to distribute the files you include in `/mix`. this can include your own recordings, public-domain works, creative commons releases, or material you've licensed from the rights holder.

## quickstart
1. **serve it**
	- run `./serve.py` to start a development server. while the server is running, you can:
		- **add new tracks** by moving audio files into the `/mix` directory, dragging them into the browser window, running `./rip.py` to rip tracks from a physical CD, or running `./buy.py` to buy tracks on iTunes (both are fine to use locally; check distribution rights before hosting publicly)
		- **reorder tracks** by dragging them up or down in the list
		- **delete tracks** with `shift + click`

2. **build it**
	- once you're happy with your mix, run `./build.py` and follow the interactive prompts to generate `manifest.json` and `service-worker.js`, which enable PWA installation and offline functionality.

3. **ship it**
	- upload the entire project directory to any static web host with HTTPS support (GitHub Pages, Neocities, AWS S3, etc.)

4. **share it**
	- once it's hosted, anyone can install your mixapp by opening the URL and following their browser's PWA installation steps:
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

## licenses
this project is licensed under the <a href="LICENSE">GNU General Public License v3.0</a>.

the <a href="https://velvetyne.fr/fonts/basteleur/">Basteleur</a> font by <a href="https://keussel.studio/">Keussel</a> (distributed by <a href="https://velvetyne.fr/">Velvetyne</a>) is licensed under the <a href="resources/fonts/Basteleur/LICENSE.txt">SIL Open Font License, version 1.1</a>.
