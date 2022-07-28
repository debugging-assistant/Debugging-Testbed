import sys
import gi
from socket import *
gi.require_version('Gtk', '3.0')
gi.require_version('WebKit', '3.0')
from gi.repository import Gtk, Gdk, WebKit

class BrowserTab(Gtk.VBox):

	def __init__(self, *args, **kwargs):
		super(BrowserTab, self).__init__(*args, **kwargs)
		go_button = Gtk.Button("Go")
		go_button.connect("clicked", self._load_url)
		self.url_bar = Gtk.Entry()
		self.url_bar.set_placeholder_text("Enter URL here...")
		self.url_bar.connect("activate", self._load_url)
		col = Gdk.color_parse("#343536")
		self.webview = WebKit.WebView()
		self.webview.modify_fg(Gtk.StateFlags.NORMAL, col)
		self.show()
		self.go_back = Gtk.Button("Back")
		self.go_back.connect("clicked", lambda x: self.webview.go_back())
		self.go_forward = Gtk.Button("Forward")
		self.go_forward.connect("clicked", lambda x: self.webview.go_forward())
		scrolled_window = Gtk.ScrolledWindow()
		scrolled_window.add(self.webview)
		find_box = Gtk.HBox()
		close_button = Gtk.Button("Close")
		close_button.connect("clicked", lambda x: find_box.hide())
		self.find_entry = Gtk.Entry()
		self.find_entry.connect("activate",lambda x: self.webview.search_text(self.find_entry.get_text(), False, True, True))
		prev_button = Gtk.Button("Previous")
		next_button = Gtk.Button("Next")
		prev_button.connect("clicked",lambda x: self.webview.search_text(self.find_entry.get_text(),False, False, True))
		next_button.connect("clicked",lambda x: self.webview.search_text(self.find_entry.get_text(),False, True, True))
		find_box.pack_start(close_button, False, False, 0)
		find_box.pack_start(self.find_entry, False, False, 0)
		find_box.pack_start(prev_button, False, False, 0)
		find_box.pack_start(next_button, False, False, 0)
		self.find_box = find_box
		self.action_label = Gtk.Label()
		action_box = Gtk.HBox()
		action_box.pack_start(self.action_label, True, True, 0)
		self.report_entry = Gtk.Entry()
		self.report_entry.set_placeholder_text("1) Enter any observations here if any... 2) Click Submit")
		submit_report = Gtk.Button("Submit")
		submit_report.connect("clicked", self.submit_report)
		report_box = Gtk.HBox()
		report_box.pack_start(self.report_entry, True, True, 0)
		report_box.pack_start(submit_report, False, False, 0)
		url_box = Gtk.HBox()
		url_box.pack_start(self.go_back, False, False, 0)
		url_box.pack_start(self.go_forward, False, False, 0)
		url_box.pack_start(self.url_bar, True, True, 0)
		url_box.pack_start(go_button, False, False, 0)
		self.pack_start(action_box, False, False, 0)
		self.pack_start(report_box, False, False, 0)
		self.pack_start(url_box, False, False, 0)
		self.pack_start(scrolled_window, True, True, 0)
		self.pack_start(find_box, False, False, 0)
		self.modify_bg(Gtk.StateFlags.NORMAL, col)
		action_box.show_all()
		report_box.show_all()
		url_box.show_all()
		scrolled_window.show_all()
		self.fault_no = 1

	def _load_url(self, widget):
		url = self.url_bar.get_text()
		if not "://" in url:
			url = "http://" + url
		self.webview.load_uri(url)

	def submit_report(self, widget):
		report = self.report_entry.get_text()
		# Send this report to logging server.
		with open("Fault_"+str(self.fault_no)+"_observations.txt","a") as inputfile:
			inputfile.write(report+"\n")
		clientSocket = socket(AF_INET, SOCK_STREAM)
		serverAddress = ('192.168.122.118',30000)
		print("--- Connecting to Fault Injection Server")
		clientSocket.connect(serverAddress)
		print("--- Connected!")

		if self.action_label.get_text() == "Action: load reddit main page with http://reddit.local:8090":
			self.action_label.set_markup("<span color='#ffffff'><big><b>Action: click on login button and login to your account</b></big></span>")
			msg = "Next Action"
			clientSocket.sendall(msg.encode())
			while True:
				data = clientSocket.recv(16)
				print("Got this: "+ data.decode())
				if data.decode()=='Proceed':
					break
		elif self.action_label.get_text() == "Action: click on login button and login to your account":
			self.action_label.set_markup("<span color='#ffffff'><big><b>Action: Choose any subreddit from 'MY SUBREDDITS'</b></big></span>")
			msg = "Next Action"
			clientSocket.sendall(msg.encode())
			while True:
				data = clientSocket.recv(16)
				if data.decode()=='Proceed':
					break
		elif self.action_label.get_text() == "Action: Choose any subreddit from 'MY SUBREDDITS'":
			self.action_label.set_markup("<span color='#ffffff'><big><b>Action: Click on a text post link to view it</b></big></span>")
			msg = "Next Action"
			clientSocket.sendall(msg.encode())
			while True:
				data = clientSocket.recv(16)
				if data.decode()=='Proceed':
					break
		elif self.action_label.get_text() == "Action: Click on a text post link to view it":
			self.action_label.set_markup("<span color='#ffffff'><big><b>Action: Upvote/Downvote a post and check by reloading the page</b></big></span>")
			msg = "Next Action"
			clientSocket.sendall(msg.encode())
			while True:
				data = clientSocket.recv(16)
				if data.decode()=='Proceed':
					break
		elif self.action_label.get_text() == "Action: Upvote/Downvote a post and check by reloading the page":
			self.action_label.set_markup("<span color='#ffffff'><big><b>Action: Submit a new text post and check if it is posted</b></big></span>")
			msg = "Next Action"
			clientSocket.sendall(msg.encode())
			while True:
				data = clientSocket.recv(16)
				if data.decode()=='Proceed':
					break
		elif self.action_label.get_text() == "Action: Submit a new text post and check if it is posted":
			self.action_label.set_markup("<span color='#ffffff'><big><b>Action: Comment on a text post and check if it is submitted</b></big></span>")
			msg = "Next Action"
			clientSocket.sendall(msg.encode())
			while True:
				data = clientSocket.recv(16)
				if data.decode()=='Proceed':
					break
		elif self.action_label.get_text() == "Action: Comment on a text post and check if it is submitted":
			self.action_label.set_markup("<span color='#ffffff'><big><b>Action: Click on a user link from a text post and check the profile</b></big></span>")
			msg = "Next Action"
			clientSocket.sendall(msg.encode())
			while True:
				data = clientSocket.recv(16)
				if data.decode()=='Proceed':
					break
		elif self.action_label.get_text() == "Action: Click on a user link from a text post and check the profile":
			self.fault_no += 1
			self.action_label.set_markup("<span color='#ffffff'><big><b>Action: load reddit main page with http://reddit.local:8090</b></big></span>")
			msg = "Next Fault"
			clientSocket.sendall(msg.encode())
			while True:
				data = clientSocket.recv(16)
				if data.decode()=='Proceed':
					break

class Browser(Gtk.Window):
	def __init__(self, *args, **kwargs):
		super(Browser, self).__init__(*args, **kwargs)
		# create notebook and tabs
		self.notebook = Gtk.Notebook()
		self.notebook.set_scrollable(True)
		# basic stuff
		self.tabs = []
		self.set_size_request(900,700)
		# create a first, empty browser tab
		col = Gdk.color_parse("#343536")
		self.tabs.append((self._create_tab(), self._create_tab_label()))
		self.notebook.append_page(*self.tabs[0])
		self.add(self.notebook)
		# connect signals
		self.connect("destroy", Gtk.main_quit)
		self.connect("key-press-event", self._key_pressed)
		self.notebook.connect("switch-page", self._tab_changed)
		self.modify_bg(Gtk.StateFlags.NORMAL, col)
		self.notebook.modify_bg(Gtk.StateFlags.NORMAL, col)
		self.notebook.show()
		self.show()

	def _tab_changed(self, notebook, current_page, index):
		if not index:
			return
		title = self.tabs[index][0].webview.get_title()
		if title:
			self.set_title(title)


	def _title_changed(self, webview, frame, title):
		current_page = self.notebook.get_current_page()
		counter = 0
		for tab, label in self.tabs:
			if tab.webview is webview:
				tab.url_bar.set_text(tab.webview.get_uri())
				label.set_markup("<span color='#ffffff'>"+title+"</span>")
				if counter == current_page:
					self._tab_changed(None, None, counter)
				break
			counter += 1

	def _create_tab_label(self):
		label = Gtk.Label()
		label.set_markup("<span color='#ffffff'>New Tab</span>")
		return label

	def _create_tab(self):
		tab = BrowserTab()
		tab.webview.connect("title-changed", self._title_changed)
		tab.action_label.set_markup("<span color='#ffffff'><big><b>Action: load reddit main page with http://reddit.local:8090</b></big></span>")
		return tab

	def _reload_tab(self):
		self.tabs[self.notebook.get_current_page()][0].webview.reload()

	def _close_current_tab(self):
		if self.notebook.get_n_pages() == 1:
			return
		page = self.notebook.get_current_page()
		current_tab = self.tabs.pop(page)
		self.notebook.remove(current_tab[0])

	def _open_new_tab(self):
		current_page = self.notebook.get_current_page()
		page_tuple = (self._create_tab(), Gtk.Label("New Tab"))
		self.tabs.insert(current_page+1, page_tuple)
		self.notebook.insert_page(page_tuple[0], page_tuple[1], current_page+1)
		self.notebook.set_current_page(current_page+1)       

	def _focus_url_bar(self):
		current_page = self.notebook.get_current_page()
		self.tabs[current_page][0].url_bar.grab_focus()

	def _raise_find_dialog(self):
		current_page = self.notebook.get_current_page()
		self.tabs[current_page][0].find_box.show_all()
		self.tabs[current_page][0].find_entry.grab_focus()

	def _key_pressed(self, widget, event):
		modifiers = Gtk.accelerator_get_default_mod_mask()
		mapping = {Gdk.KEY_r: self._reload_tab,Gdk.KEY_w: self._close_current_tab,Gdk.KEY_t: self._open_new_tab, Gdk.KEY_l: self._focus_url_bar,Gdk.KEY_f: self._raise_find_dialog,Gdk.KEY_q: Gtk.main_quit}
		if event.state & modifiers == Gdk.ModifierType.CONTROL_MASK and event.keyval in mapping:
			mapping[event.keyval]()

if __name__ == "__main__":
	Gtk.init(sys.argv)
	browser = Browser()
	Gtk.main()