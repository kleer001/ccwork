# The bug that turned my session manager into a desktop app

I started ccwork as a one-evening project. A small notification, a renamed terminal tab, and a script to glue them together. That was the whole product. The README took longer to write than the code.

For a few days it did the job. I added a wrapper around the `claude` command that picked up where the last conversation had left off, an installer that could cleanly undo itself, and — because no tool ships without one — a comparison table against the competition. The first draft of that table came out snarky. The second replaced the snark with links to specific bugs in the competing projects. The third rewrote the whole thing in positive framing, crediting the other tools for what they did well. It's a useful exercise. You learn what your tool is actually for when you're forced to articulate what it isn't.

Then I tried to add a spinner.

The idea was small. While Claude was thinking, animate the tab name with a braille spinner cycling through 10 frames, 10 times a second. The wrapper would fork a background loop that asked the terminal multiplexer to rename the tab on a timer.

It looked great when I was sitting in front of it. As soon as I switched to another tab to read my email, the spinner started overwriting *that* tab's name instead.

Here's what I didn't know. The rename command in this multiplexer renames whichever tab is currently focused, not the tab where the calling process lives. And there was no environment variable I could read to tell my background process which tab it was attached to. If I started Claude in tab 3 and switched to tab 7, my spinner cheerfully renamed tab 7 ten times a second.

I pulled the spinner out. Then I pulled the same rename out of the notification hooks, because they had the same bug — those hooks fire after I've already moved on, so they always race against focus.

That was when I admitted the multiplexer was the wrong substrate. There was no clickable list of repos. No stable header showing which repo I was in. No persistent alert history — just transient OS toasts that vanished as soon as you blinked. And every piece of UI I wanted to add was at the mercy of somebody else's focus model.

So I rewrote it as a desktop app.

The new ccwork is a window with a sidebar of repos on the left and an embedded terminal on the right. Each repo gets its own real terminal, the same one I'd been using all along, but the desktop app owns the frame around it: the sidebar with branch names and unread badges, the alerts panel, the preferences dialog. When Claude finishes a turn or pings for input, a small helper script forwards the event to the app over a local socket, and the right repo lights up. Color schemes and font changes can be picked in a dialog and pushed live to every running terminal without restarting anything. By the end of that work session there were 82 passing tests.

The first stretch after the pivot was a parade of small embedding bugs. Live font changes silently disappeared because the terminal had a setting, off by default, that refuses font changes from the outside. The desktop chrome ignored my chosen color scheme because the underlying widget toolkit was quietly inheriting the system style. Keyboard zoom shortcuts didn't reach the app at all — the embedded terminal grabs input before anything else gets a look — and the fix was to ask the windowing system to route those specific key combinations to the outer window first, before the terminal could swallow them. The same trick wired up tab cycling and a right-click menu.

Then the cleanup. The README, which had drifted into a reference manual, was trimmed to an install section and a collapsed expandable block for the manual flow. A one-line install script became the front door. The automated test suite had been failing on every commit, and the cause turned out to be a Python version that had moved past what the GUI library shipped prebuilt binaries for, plus a few system libraries the offscreen test mode quietly depends on. I deleted a session-persistence path I'd added during the pivot but never actually wired into anything, along with two helper modules whose only consumers were code I'd just deleted.

And the spinner came back. This time it's a small braille animation drawn directly in the sidebar, redrawn 10 times a second, but only when at least one repo is actually working. Same animation. Different surface — one I owned end to end.

That's the lesson I'd take from ccwork, if I were the kind of writer who liked to end on a lesson: when your interface keeps fighting the layer underneath it, the layer underneath is the bug.
