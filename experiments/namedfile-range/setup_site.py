"""Create the Plone site and a deterministic big File. Run with ``zconsole run``.

    zconsole run zope.conf setup_site.py --size 67108864
"""

import argparse
import random
import sys

import transaction
from AccessControl.SecurityManagement import newSecurityManager
from AccessControl.SpecialUsers import system
from plone.dexterity.utils import createContentInContainer
from plone.namedfile.file import NamedBlobFile
from Products.CMFPlone.factory import addPloneSite
from Testing.makerequest import makerequest
from zope.component.hooks import setSite

parser = argparse.ArgumentParser()
parser.add_argument("--size", type=int, required=True)
args, _ = parser.parse_known_args(sys.argv[1:])  # zconsole leaves its own argv in place

newSecurityManager(None, system)
app = makerequest(app)  # noqa: F821, provided by zconsole

addPloneSite(
    app,
    "plone",
    title="wsgi-sandbox",
    setup_content=False,
    extension_ids=("plone.app.contenttypes:default",),
)
site = app["plone"]
setSite(site)

# The client regenerates the same bytes, to check every slice it gets back.
data = random.Random(42).randbytes(args.size)
big = createContentInContainer(
    site,
    "File",
    checkConstraints=False,
    id="big-file",
    title="Big file",
    file=NamedBlobFile(data, filename="big.bin", contentType="application/octet-stream"),
)
transaction.commit()
print(f"created {big.absolute_url_path()} with {args.size} bytes")
