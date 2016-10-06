# Copyright (C) 2014-2016 New York University
# This file is part of ReproZip which is released under the Revised BSD License
# See file LICENSE for full license details.

from __future__ import division, print_function, unicode_literals

import yaml

from PyQt4 import QtCore, QtGui

import reprounzip_qt.reprounzip_interface as reprounzip
from reprounzip_qt.gui.common import ROOT, handle_error


class FilesManager(QtGui.QDialog):
    def __init__(self, directory, unpacker=None, root=None, **kwargs):
        super(FilesManager, self).__init__(**kwargs)
        self.directory = directory
        self.unpacker = unpacker
        self.root = root

        layout = QtGui.QHBoxLayout()

        self.files_widget = QtGui.QListWidget(
            selectionMode=QtGui.QListWidget.SingleSelection)
        self.files_widget.itemSelectionChanged.connect(self._file_changed)
        layout.addWidget(self.files_widget)

        right_layout = QtGui.QGridLayout()
        right_layout.addWidget(QtGui.QLabel("name:"), 0, 0)
        self.f_name = QtGui.QLineEdit('', readOnly=True)
        right_layout.addWidget(self.f_name, 0, 1)
        right_layout.addWidget(QtGui.QLabel("Path:"), 1, 0)
        self.f_path = QtGui.QLineEdit('', readOnly=True)
        right_layout.addWidget(self.f_path, 1, 1)
        right_layout.addWidget(QtGui.QLabel("Current:"), 2, 0)
        self.f_status = QtGui.QLineEdit('', readOnly=True)
        right_layout.addWidget(self.f_status, 2, 1)
        self.b_upload = QtGui.QPushButton("Upload a replacement",
                                          enabled=False)
        self.b_upload.clicked.connect(self._upload)
        right_layout.addWidget(self.b_upload, 3, 0, 1, 2)
        self.b_download = QtGui.QPushButton("Download to disk", enabled=False)
        self.b_download.clicked.connect(self._download)
        right_layout.addWidget(self.b_download, 4, 0, 1, 2)
        self.b_reset = QtGui.QPushButton("Reset file", enabled=False)
        self.b_reset.clicked.connect(self._reset)
        right_layout.addWidget(self.b_reset, 5, 0, 1, 2)
        right_layout.setRowStretch(6, 1)
        layout.addLayout(right_layout)

        self.setLayout(layout)

        self.files_status = reprounzip.FilesStatus(directory)

        for file_status in self.files_status:
            text = "[%s%s] %s" % (("I" if file_status.is_input else ''),
                                  ("O" if file_status.is_output else ''),
                                  file_status.name)
            self.files_widget.addItem(text)

    def _file_changed(self):
        selected = [i.row() for i in self.files_widget.selectedIndexes()]
        if not selected:
            self.f_name.setText('')
            self.f_path.setText('')
            self.f_status.setText('')
            self.b_upload.setEnabled(False)
            self.b_download.setEnabled(False)
            self.b_reset.setEnabled(False)
        else:
            file_status = self.files_status[selected[0]]
            self.b_upload.setEnabled(True)
            self.b_download.setEnabled(True)
            self.b_reset.setEnabled(False)
            self.f_name.setText(file_status.name)
            self.f_path.setText(file_status.path)
            self.f_status.setEnabled(False)
            if file_status.assigned is None:
                self.f_status.setText("(original)")
                self.b_reset.setEnabled(False)
            elif file_status.assigned is False:
                self.f_status.setText("(not created)")
            elif file_status.assigned is True:
                self.f_status.setText("(generated)")
            else:
                self.f_status.setText(file_status.assigned)
                self.f_status.setEnabled(True)

    def _upload(self):
        selected = self.files_widget.selectedIndexes()[0].row()
        file_status = self.files_status[selected]
        picked = QtGui.QFileDialog.getOpenFileName(
            self, "Pick file to upload",
            QtCore.QDir.currentPath())
        if picked:
            handle_error(self, reprounzip.upload(
                self.directory, file_status.name, picked,
                unpacker=self.unpacker, root=self.root))
            self._file_changed()

    def _download(self):
        selected = self.files_widget.selectedIndexes()[0].row()
        file_status = self.files_status[selected]
        picked = QtGui.QFileDialog.getSaveFileName(
            self, "Pick destination",
            QtCore.QDir.currentPath() + '/' + file_status.name)
        if picked:
            handle_error(self, reprounzip.download(
                self.directory, file_status.name, picked,
                unpacker=self.unpacker, root=self.root))
            self._file_changed()

    def _reset(self):
        selected = self.files_widget.selectedIndexes()[0].row()
        file_status = self.files_status[selected]
        handle_error(self, reprounzip.upload(
            self.directory, file_status.name, None,
            unpacker=self.unpacker, root=self.root))
        self._file_changed()


class RunTab(QtGui.QWidget):
    """The main window, that allows you to run/change an unpacked experiment.
    """
    directory = None
    unpacker = None

    def __init__(self, unpacked_directory='', **kwargs):
        super(RunTab, self).__init__(**kwargs)

        layout = QtGui.QGridLayout()
        layout.addWidget(QtGui.QLabel("Experiment directory:"), 0, 0)
        self.directory_widget = QtGui.QLineEdit(unpacked_directory)
        self.directory_widget.editingFinished.connect(self._directory_changed)
        layout.addWidget(self.directory_widget, 0, 1)
        browse = QtGui.QPushButton("Browse")
        browse.clicked.connect(self._browse)
        layout.addWidget(browse, 0, 2)

        layout.addWidget(QtGui.QLabel("Unpacker:"), 1, 0,
                         QtCore.Qt.AlignTop)
        self.unpacker_widget = QtGui.QLabel("-")
        layout.addWidget(self.unpacker_widget, 1, 1, 1, 2)

        layout.addWidget(QtGui.QLabel("Input/output files:"), 2, 0,
                         QtCore.Qt.AlignTop)
        self.files_button = QtGui.QPushButton("Manage files", enabled=False)
        self.files_button.clicked.connect(self._open_files_manager)
        layout.addWidget(self.files_button, 2, 1, 1, 2)

        layout.addWidget(QtGui.QLabel("Runs:"), 3, 0,
                         QtCore.Qt.AlignTop)
        self.runs_widget = QtGui.QListWidget(
            selectionMode=QtGui.QListWidget.MultiSelection)
        layout.addWidget(self.runs_widget, 3, 1, 3, 1)
        select_all = QtGui.QPushButton("Select All")
        select_all.clicked.connect(self.runs_widget.selectAll)
        layout.addWidget(select_all, 3, 2)
        deselect_all = QtGui.QPushButton("Deselect All")
        deselect_all.clicked.connect(self.runs_widget.clearSelection)
        layout.addWidget(deselect_all, 4, 2)

        layout.addWidget(QtGui.QLabel("Elevate privileges:"), 6, 0)
        self.root = QtGui.QComboBox(editable=False)
        self.root.addItems(ROOT.TEXT)
        layout.addWidget(self.root, 6, 1, 1, 2)

        layout.addWidget(QtGui.QLabel("X11 display:"), 7, 0)
        self.x11_enabled = QtGui.QCheckBox("enabled", checked=False)
        layout.addWidget(self.x11_enabled, 7, 1, 1, 2)

        layout.setRowStretch(8, 1)

        buttons = QtGui.QHBoxLayout()
        buttons.addStretch(1)
        self.run_widget = QtGui.QPushButton("Run experiment")
        self.run_widget.clicked.connect(self._run)
        buttons.addWidget(self.run_widget)
        self.destroy_widget = QtGui.QPushButton("Destroy unpacked experiment")
        self.destroy_widget.clicked.connect(self._destroy)
        buttons.addWidget(self.destroy_widget)
        layout.addLayout(buttons, 9, 0, 1, 3)

        self.setLayout(layout)

        self._directory_changed()

    def _browse(self):
        picked = QtGui.QFileDialog.getExistingDirectory(
            self, "Pick directory",
            QtCore.QDir.currentPath())
        if picked:
            self.directory_widget.setText(picked)
            self._directory_changed()

    def _directory_changed(self, new_dir=None, force=False):
        if not force and self.directory_widget.text() == self.directory:
            return
        self.directory = self.directory_widget.text()

        unpacker = reprounzip.check_directory(self.directory)

        self.runs_widget.clear()
        if unpacker is not None:
            with open(self.directory + '/config.yml') as fp:
                self.config = yaml.load(fp)
            self.run_widget.setEnabled(True)
            self.destroy_widget.setEnabled(True)
            self.files_button.setEnabled(True)
            self.unpacker = unpacker
            self.unpacker_widget.setText(unpacker)
            for run in self.config['runs']:
                self.runs_widget.addItem(' '.join(reprounzip.shell_escape(arg)
                                                  for arg in run['argv']))
            self.runs_widget.selectAll()
        else:
            self.run_widget.setEnabled(False)
            self.destroy_widget.setEnabled(False)
            self.files_button.setEnabled(False)
            self.unpacker = None
            self.unpacker_widget.setText("-")

    def _run(self):
        runs = sorted(i.row() for i in self.runs_widget.selectedIndexes())
        handle_error(self, reprounzip.run(
            self.directory, runs=runs,
            unpacker=self.unpacker,
            x11_enabled=self.x11_enabled.isChecked(),
            root=ROOT.INDEX_TO_OPTION[self.root.currentIndex()]))

    def _destroy(self):
        handle_error(self, reprounzip.destroy(
            self.directory, unpacker=self.unpacker,
            root=ROOT.INDEX_TO_OPTION[self.root.currentIndex()]))
        self._directory_changed(force=True)

    def _open_files_manager(self):
        manager = FilesManager(
            parent=self,
            directory=self.directory_widget.text(),
            unpacker=self.unpacker,
            root=ROOT.INDEX_TO_OPTION[self.root.currentIndex()])
        manager.exec_()

    def set_directory(self, directory, root=None):
        self.root.setCurrentIndex(ROOT.OPTION_TO_INDEX[root])
        self.directory_widget.setText(directory)
        self._directory_changed()
