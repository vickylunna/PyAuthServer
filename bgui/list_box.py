"""
ListBoxes make use of a ListBoxRenderer. The default ListBoxRenderer simply
displays an item's string representation. To make your own ListBoxRenderer
create a class that has a render_item() method that accepts the item to be rendered
and returns a widget to render.

Here is an simple example of using the ListBox widget::

	class MySys(bgui.System):
		def lb_click(self, lb):
			print(lb.selected)

		def __init__(self):
			bgui.System.__init__(self)

			items = ["One", "Two", 4, 4.6]
			self.frame = bgui.Frame(self, 'window', border=2, size=[0.5, 0.5],
				options=bgui.BGUI_DEFAULT|bgui.BGUI_CENTERED)
			self.lb = bgui.ListBox(self.frame, "lb", items=items, padding=0.05, size=[0.9, 0.9], pos=[0.05, 0.05])
			self.lb.on_click = self.lb_click

			# ... rest of __init__

"""

from .widget import Widget, BGUI_DEFAULT, BGUI_MOUSE_CLICK
from .frame import Frame
from .label import Label

from itertools import islice

class ListBoxRenderer():
	"""Base class for rendering an item in a ListBox"""
	def __init__(self, listbox):
		"""
		:param listbox: the listbox the renderer will be used with (used for parenting)
		"""
		self.label = Label(listbox, "label")

	def render_item(self, item):
		"""Creates and returns a :py:class:`bgui.label.Label` representation of the supplied item

		:param item: the item to be rendered
		:rtype: :py:class:`bgui.label.Label`
		"""
		self.label.text = item.__repr__()

		return self.label


class ListBox(Widget):
	"""Widget for displaying a list of data"""

	theme_section = 'ListBox'
	theme_options = {
				'HighlightColor1': (1, 1, 1, 1),
				'HighlightColor2': (0, 0, 1, .5),
				'HighlightColor3': (0, 0, 1, .5),
				'HighlightColor4': (0, 0, 1, 1),
				'Border': 1,
				'Padding': 0,
				}

	def __init__(self, parent, name, items=[], padding=0, aspect=None, size=[1, 1], pos=[0, 0], length=None,
                 auto_scale=True, item_height=0.1, shift=0, sub_theme='', options=BGUI_DEFAULT):
		"""
		:param parent: the widget's parent
		:param name: the name of the widget
		:param items: the items to fill the list with (can also be changed via ListBox.items)
		:param padding: the amount of extra spacing to put between items (can also be changed via ListBox.padding)
		:param aspect: constrain the widget size to a specified aspect ratio
		:param size: a tuple containing the width and height
		:param pos: a tuple containing the x and y position
		:param sub_theme: name of a sub_theme defined in the theme file (similar to CSS classes)
		:param options:	various other options
		"""

		Widget.__init__(self, parent, name, aspect=aspect, size=size, pos=pos, sub_theme='', options=options)

		self._items = items
		if padding:
			self._padding = padding
		else:
			self._padding = self.theme['Padding']

		self.highlight = Frame(self, "frame", border=1, size=[1, 1], pos=[0, 0])
		self.highlight.visible = False
		self.highlight.border = self.theme['Border']
		self.highlight.colors = [
				self.theme['HighlightColor1'],
				self.theme['HighlightColor2'],
				self.theme['HighlightColor3'],
				self.theme['HighlightColor4'],
				]

		self.selected = None
		self._on_select = None
		self._spatial_map = {}

		self._renderer = ListBoxRenderer(self)

		self._shift = shift
		self._length = length
		self._item_height = item_height
		self._scale = auto_scale

	def _del__(self):
		super().__del__()
	##
	# These props are created simply for documentation purposes
	#
	
	@property
	def on_select(self):
		return self._on_select
	
	@on_select.setter
	def on_select(self, value):
		self._on_select = value
	
	@property
	def length(self):
		if self._length is None:
			return len(self.items)
		return self._length
	
	@length.setter
	def length(self, value):
		self._length = value
	
	@property
	def shift(self):
		return self._shift
	
	@shift.setter
	def shift(self, value):
		self._shift = value
	
	@property
	def renderer(self):
		"""The ListBoxRenderer to use to display items"""
		return self._renderer

	@renderer.setter
	def renderer(self, value):
		self._renderer = value

	@property
	def padding(self):
		"""The amount of extra spacing to put between items"""
		return self._padding

	@padding.setter
	def padding(self, value):
		self._padding = value

	@property
	def items(self):
		"""The list of items to display in the ListBox"""
		return self._items

	@items.setter
	def items(self, value):
		self._items = value
		self._spatial_map.clear()
	
	def can_draw(self, item):
		if not item in self.items:
			return False
		return 0 <= (self.items.index(item) - self.shift) < self.length
	
	def _draw(self):
		for index, item in enumerate(self.items):			
			widget = self.renderer.render_item(item)
			
			shifted_index = index - self.shift
			# Max widget height without padding
			widget_max_height = max((self.length - 1), 1) / self.length# ** 2
			# Widget height considering padding (a scalar)
			widget_height = (widget_max_height * (1 - self.padding)) if self._scale else self._item_height
			# Shift to position widget within bounds
			y_shift =  ((shifted_index + 1) * (widget_height  + self.padding))
			
			widget.position = [0, (1 - y_shift)]
			widget.size = [1, widget_height]
			
			self._spatial_map[item] = [i[:] for i in widget.gl_position]  # Make a full copy
			
			# If can draw widget (not shifted or truncated)
			if self.can_draw(item):
				widget._draw()

			if self.selected == item:
				self.highlight.gl_position = [i[:] for i in widget.gl_position]
				self.highlight.visible = True

	def _handle_mouse(self, pos, event):

		Widget._handle_mouse(self, pos, event)
		if event == BGUI_MOUSE_CLICK:
			for item, gl_position in self._spatial_map.items():
				if (gl_position[0][0] <= pos[0] <= gl_position[1][0]) and \
					(gl_position[0][1] <= pos[1] <= gl_position[2][1]):
						if self.can_draw(item): 
							self.selected = item
							if self.on_select:
								self.on_select(self, item)
						break
				
