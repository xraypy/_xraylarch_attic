import wx
import time
import os

MODNAME = '_builtin'

def ensuremod(_larch):
    if _larch is not None:
        symtable = _larch.symtable
        if not symtable.has_group(MODNAME):
            symtable.newgroup(MODNAME)

def _gcd(wxparent=None, _larch=None, **kws):
    """Directory Browser to Change Directory"""
    dlg = wx.DirDialog(wxparent, message='Choose Directory',
                       style = wx.DD_DEFAULT_STYLE)
    path = None
    if dlg.ShowModal() == wx.ID_OK:
        path = dlg.GetPath()
    dlg.Destroy()
    if path is not None:
        os.chdir(path)
    return os.getcwd()

def _fileprompt(wxparent=None, _larch=None,
                mode='open', multi=True,
                message = None,
                fname=None, choices=None, **kws):
    """Bring up File Browser for opening or saving file.
    Returns name of selected file.

    options:
       mode:  one of 'open' or 'save'
       message: text to display in top window bar

    """
    symtable = ensuremod(_larch)
    if fname is None:
        try:
            fname = symtable.get_symbol("%s.default_filename" % MODNAME)
        except:
            fname = ''
    if choices  is None:
        try:
            choices = symtable.get_symbol("%s.ext_choices" % MODNAME)
        except:
            choices = 'All Files (*.*)|*.*'

    if mode == 'open':
        style = wx.OPEN|wx.CHANGE_DIR
        if multi:
            style = style|wx.MULTIPLE
        if message is None:
            message = 'Open File '
    else:
        style = wx.SAVE|wx.CHANGE_DIR
        if message is None:
            message = 'Save As '
    # print 'FileDialog ', wxparent, message, fname , choices, style
    dlg = wx.FileDialog(parent=wxparent, message=message,
                        defaultDir = os.getcwd(),
                        defaultFile= fname,
                        wildcard = choices,
                        style=style)
    path = None
    if dlg.ShowModal() == wx.ID_OK:
        path = dlg.GetPath()
    dlg.Destroy()

    return path

def registerLarchPlugin():
    return (MODNAME, {'gcd': _gcd,
                      'fileprompt': _fileprompt})

