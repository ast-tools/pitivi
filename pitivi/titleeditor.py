# -*- coding: utf-8 -*-
# Pitivi video editor
# Copyright (c) 2012, Matas Brazdeikis <matas@brazdeikis.lt>
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this program; if not, write to the
# Free Software Foundation, Inc., 51 Franklin St, Fifth Floor,
# Boston, MA 02110-1301, USA.
import os
from gettext import gettext as _

from gi.repository import GES
from gi.repository import Gst
from gi.repository import Gtk
from gi.repository import Pango

from pitivi.configure import get_ui_dir
from pitivi.dialogs.prefs import PreferencesDialog
from pitivi.settings import GlobalSettings
from pitivi.utils.loggable import Loggable
from pitivi.utils.timeline import SELECT
from pitivi.utils.ui import argb_to_gdk_rgba
from pitivi.utils.ui import fix_infobar
from pitivi.utils.ui import gdk_rgba_to_argb
from pitivi.utils.widgets import ColorPickerButton

GlobalSettings.addConfigOption('titleClipLength',
                               section="user-interface",
                               key="title-clip-length",
                               default=5000,
                               notify=True)

PreferencesDialog.addNumericPreference('titleClipLength',
                                       section="timeline",
                                       label=_("Title clip duration"),
                                       description=_(
                                           "Default clip length (in milliseconds) of titles when inserting on the timeline."),
                                       lower=1)

FOREGROUND_DEFAULT_COLOR = 0xFFFFFFFF  # White
BACKGROUND_DEFAULT_COLOR = 0x00000000  # Transparent
DEFAULT_FONT_DESCRIPTION = "Sans 36"
DEFAULT_VALIGNMENT = "absolute"
DEFAULT_HALIGNMENT = "absolute"


class TitleEditor(Loggable):
    """Widget for configuring a title.

    Attributes:
        app (Pitivi): The app.
        _project (Project): The project.
    """

    def __init__(self, app):
        Loggable.__init__(self)
        self.app = app
        self.settings = {}
        self.source = None
        self._project = None
        self._selection = None

        self._setting_props = False
        self._children_props_handler = None

        self._createUI()
        # Updates the UI.
        self.set_source(None)

        self.app.project_manager.connect_after(
            "new-project-loaded", self._newProjectLoadedCb)

    def _createUI(self):
        builder = Gtk.Builder()
        builder.add_from_file(os.path.join(get_ui_dir(), "titleeditor.ui"))
        builder.connect_signals(self)
        self.widget = builder.get_object("box1")  # To be used by tabsmanager
        self.infobar = builder.get_object("infobar")
        fix_infobar(self.infobar)
        self.editing_box = builder.get_object("base_table")

        self.textarea = builder.get_object("textview")

        self.textbuffer = self.textarea.props.buffer
        self.textbuffer.connect("changed", self._textChangedCb)

        self.font_button = builder.get_object("fontbutton1")
        self.foreground_color_button = builder.get_object("fore_text_color")
        self.background_color_button = builder.get_object("back_color")

        self.color_picker_foreground_widget = ColorPickerButton()
        self.color_picker_foreground_widget.show()
        self.color_picker_foreground = builder.get_object("color_picker_foreground")
        self.color_picker_foreground.add(self.color_picker_foreground_widget)
        self.color_picker_foreground_widget.connect("value-changed", self._color_picker_value_changed_cb, self.foreground_color_button, "color")

        self.color_picker_background_widget = ColorPickerButton()
        self.color_picker_background_widget.show()
        self.background_color_picker = builder.get_object("color_picker_background")
        self.background_color_picker.add(self.color_picker_background_widget)
        self.color_picker_background_widget.connect("value-changed", self._color_picker_value_changed_cb, self.background_color_button, "foreground-color")

        settings = ["valignment", "halignment", "x-absolute", "y-absolute"]
        for setting in settings:
            self.settings[setting] = builder.get_object(setting)

        for n, en in list({_("Absolute"): "absolute",
                           _("Top"): "top",
                           _("Center"): "center",
                           _("Bottom"): "bottom",
                           _("Baseline"): "baseline"}.items()):
            self.settings["valignment"].append(en, n)

        for n, en in list({_("Absolute"): "absolute",
                           _("Left"): "left",
                           _("Center"): "center",
                           _("Right"): "right"}.items()):
            self.settings["halignment"].append(en, n)

    def _setChildProperty(self, name, value):
        with self.app.action_log.started("Title change property",
                                         toplevel=True):
            self._setting_props = True
            try:
                res = self.source.set_child_property(name, value)
                assert res
            finally:
                self._setting_props = False

    def _color_picker_value_changed_cb(self, widget, colorButton, colorLayer):
        argb = 0
        argb += (1 * 255) * 256 ** 3
        argb += float(widget.color_r) * 256 ** 2
        argb += float(widget.color_g) * 256 ** 1
        argb += float(widget.color_b) * 256 ** 0
        self.debug("Setting text %s to %x", colorLayer, argb)
        self._setChildProperty(colorLayer, argb)
        rgba = argb_to_gdk_rgba(argb)
        colorButton.set_rgba(rgba)

    def _backgroundColorButtonCb(self, widget):
        color = gdk_rgba_to_argb(widget.get_rgba())
        self.debug("Setting title background color to %x", color)
        self._setChildProperty("foreground-color", color)

    def _frontTextColorButtonCb(self, widget):
        color = gdk_rgba_to_argb(widget.get_rgba())
        self.debug("Setting title foreground color to %x", color)
        # TODO: Use set_text_color when we work with TitleSources instead of
        # TitleClips
        self._setChildProperty("color", color)

    def _fontButtonCb(self, widget):
        font_desc = widget.get_font_desc().to_string()
        self.debug("Setting font desc to %s", font_desc)
        self._setChildProperty("font-desc", font_desc)

    def _updateFromSource(self, source):
        self.textbuffer.set_text(source.get_child_property("text")[1] or "")
        self.settings['x-absolute'].set_value(source.get_child_property("x-absolute")[1])
        self.settings['y-absolute'].set_value(source.get_child_property("y-absolute")[1])
        self.settings['valignment'].set_active_id(
            source.get_child_property("valignment")[1].value_name)
        self.settings['halignment'].set_active_id(
            source.get_child_property("halignment")[1].value_name)
        self._updateWidgetsVisibility()

        font_desc = Pango.FontDescription.from_string(
            source.get_child_property("font-desc")[1])
        self.font_button.set_font_desc(font_desc)

        color = argb_to_gdk_rgba(source.get_child_property("color")[1])
        self.foreground_color_button.set_rgba(color)

        color = argb_to_gdk_rgba(source.get_child_property("foreground-color")[1])
        self.background_color_button.set_rgba(color)

    def _textChangedCb(self, unused_updated_obj):
        if not self.source:
            # Nothing to update.
            return

        text = self.textbuffer.props.text
        self.log("Source text updated to %s", text)
        self._setChildProperty("text", text)

    def _update_source_cb(self, updated_obj):
        """Handles changes in the advanced property widgets at the bottom."""
        if not self.source:
            # Nothing to update.
            return

        for name, obj in list(self.settings.items()):
            if obj == updated_obj:
                if name == "valignment":
                    value = obj.get_active_id()
                    self._updateWidgetsVisibility()
                elif name == "halignment":
                    value = obj.get_active_id()
                    self._updateWidgetsVisibility()
                else:
                    value = obj.get_value()
                self._setChildProperty(name, value)
                return

    def _updateWidgetsVisibility(self):
        visible = self.settings["valignment"].get_active_id() == "absolute"
        self.settings["y-absolute"].set_visible(visible)
        visible = self.settings["halignment"].get_active_id() == "absolute"
        self.settings["x-absolute"].set_visible(visible)

    def set_source(self, source):
        """Sets the clip to be edited with this editor.

        Args:
            source (GES.TitleSource): The source of the clip.
        """
        self.debug("Source set to %s", source)
        if self._children_props_handler is not None:
            self.source.disconnect(self._children_props_handler)
            self._children_props_handler = None
        self.source = None
        if source:
            assert isinstance(source, GES.TextOverlay) or \
                isinstance(source, GES.TitleSource)
            self._updateFromSource(source)
            self.source = source
            self.infobar.hide()
            self.editing_box.show()
            self._children_props_handler = self.source.connect('deep-notify',
                                                               self._source_deep_notify_cb)
        else:
            self.infobar.show()
            self.editing_box.hide()

    def _createCb(self, unused_button):
        title_clip = GES.TitleClip()
        duration = self.app.settings.titleClipLength * Gst.MSECOND
        title_clip.set_duration(duration)
        self.app.gui.editor.timeline_ui.insert_clips_on_first_layer([title_clip])
        # Now that the clip is inserted in the timeline, it has a source which
        # can be used to set its properties.
        source = title_clip.get_children(False)[0]
        properties = {"text": "",
                      "foreground-color": BACKGROUND_DEFAULT_COLOR,
                      "color": FOREGROUND_DEFAULT_COLOR,
                      "font-desc": DEFAULT_FONT_DESCRIPTION,
                      "valignment": DEFAULT_VALIGNMENT,
                      "halignment": DEFAULT_HALIGNMENT}
        for prop, value in properties.items():
            res = source.set_child_property(prop, value)
            assert res, prop
        self._selection.setSelection([title_clip], SELECT)

    def _source_deep_notify_cb(self, source, unused_gstelement, pspec):
        """Handles updates in the TitleSource backing the current TitleClip."""
        if self._setting_props:
            self._project.pipeline.commit_timeline()
            return

        control_binding = self.source.get_control_binding(pspec.name)
        if control_binding:
            self.debug("Not handling %s as it is being interpolated",
                       pspec.name)
            return

        if pspec.name == "text":
            res, value = self.source.get_child_property(pspec.name)
            assert res, pspec.name
            if self.textbuffer.props.text == value or "":
                return
            self.textbuffer.props.text = value
        elif pspec.name in ["x-absolute", "y-absolute"]:
            res, value = self.source.get_child_property(pspec.name)
            assert res, pspec.name
            if self.settings[pspec.name].get_value() == value:
                return
            self.settings[pspec.name].set_value(value)
        elif pspec.name in ["valignment", "halignment"]:
            res, value = self.source.get_child_property(pspec.name)
            assert res, pspec.name
            value = value.value_name
            if self.settings[pspec.name].get_active_id() == value:
                return
            self.settings[pspec.name].set_active_id(value)
        elif pspec.name == "font-desc":
            res, value = self.source.get_child_property(pspec.name)
            assert res, pspec.name
            if self.font_button.get_font_desc() == value:
                return
            font_desc = Pango.FontDescription.from_string(value)
            self.font_button.set_font_desc(font_desc)
        elif pspec.name == "color":
            res, value = self.source.get_child_property(pspec.name)
            assert res, pspec.name
            color = argb_to_gdk_rgba(value)
            if color == self.foreground_color_button.get_rgba():
                return
            self.foreground_color_button.set_rgba(color)
        elif pspec.name == "foreground-color":
            res, value = self.source.get_child_property(pspec.name)
            assert res, pspec.name
            color = argb_to_gdk_rgba(value)
            if color == self.background_color_button.get_rgba():
                return
            self.background_color_button.set_rgba(color)

        self._project.pipeline.commit_timeline()

    def _newProjectLoadedCb(self, unused_project_manager, project):
        if self._selection is not None:
            self._selection.disconnect_by_func(self._selectionChangedCb)
            self._selection = None
        if project:
            self._selection = project.ges_timeline.ui.selection
            self._selection.connect('selection-changed', self._selectionChangedCb)
        self._project = project

    def _selectionChangedCb(self, selection):
        selected_clip = selection.getSingleClip(GES.TitleClip)
        source = None
        if selected_clip:
            for child in selected_clip.get_children(False):
                if isinstance(child, GES.TitleSource):
                    source = child
                    break

        self.set_source(source)
