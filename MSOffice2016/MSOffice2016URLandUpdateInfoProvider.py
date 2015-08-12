#!/usr/bin/env python
#
# Copyright 2015 Allister Banks, wholesale lifted from code by Greg Neagle
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


import plistlib
import urllib2
import re

from operator import itemgetter

from autopkglib import Processor, ProcessorError


__all__ = ["MSOffice2016URLandUpdateInfoProvider"]

# Defaults to 'en-US' as the installers and updates seem to be
# multilingual.
CULTURE_CODE = "0409"
BASE_URL = "http://www.microsoft.com/mac/autoupdate/%s15.xml"
PROD_DICT = {
    'Excel':'XCEL',
    'OneNote':'ONMC',
    'Outlook':'OPIM',
    'PowerPoint':'PPT3',
    'Word':'MSWD',
}

class MSOffice2016URLandUpdateInfoProvider(Processor):
    """Provides a download URL for the most recent version of MS Office 2016."""
    input_variables = {
        "product": {
            "required": True,
            "description": "Name of product to fetch, e.g. Excel.",
        },
        "version": {
            "required": False,
            "default": "latest",
            "description": ("Update version to fetch. Currently the only "
                            "supported value is 'latest', which is the "
                            "default."),
        },
    }
    output_variables = {
        "url": {
            "description": "URL to the latest installer.",
        },
        "additional_pkginfo": {
            "description":
                "Some pkginfo fields extracted from the Microsoft metadata.",
        },
        "version": {
            "description":
                ("The version of the update as extracted from the Microsoft "
                 "metadata.")
        }
    }
    description = __doc__

    def sanityCheckExpectedTriggers(self, item):
        """Raises an exeception if the Trigger Condition or
        Triggers for an update don't match what we expect.
        Protects us if these change in the future."""
        # MS currently uses "Registered File" placeholders, which get replaced
        # with the bundle of a given application ID. In other words, this is
        # the bundle version of the app itself.
        if not item.get("Trigger Condition") == ["and", "Registered File"]:
            raise ProcessorError(
                "Unexpected Trigger Condition in item %s: %s"
                % (item["Title"], item["Trigger Condition"]))
        if not "Registered File" in item.get("Triggers", {}):
            raise ProcessorError(
                "Missing expected 'and Registered File' Trigger in item "
                "%s" % item["Title"])

    def getInstallsItems(self, item):
        """Attempts to parse the Triggers to create an installs item using
        only manifest data, making the assumption that CFBundleVersion and
        CFBundleShortVersionString are equal."""
        self.sanityCheckExpectedTriggers(item)
        version = self.getVersion(item)
        installs_item = {
            "CFBundleShortVersionString": version,
            "CFBundleVersion": version,
            "path": ("/Applications/Microsoft %s.app" % self.env["product"]),
            "type": "application",
        }
        return [installs_item]

    def getVersion(self, item):
        """Extracts the version of the update item."""
        # We currently expect the version at the end of the Title key,
        # e.g.: "Microsoft Excel Update 15.10.0"
        # item["Title"] = "Microsoft Excel Update 15.10"
        match = re.search(
            r"( Update )(?P<version>\d+\.\d+(\.\d)*)", item["Title"])
        if not match:
            raise ProcessorError(
                "Error validating Office 2016 version extracted "
                "from Title manifest value: '%s'" % item["Title"])
        version = match.group('version')
        return version

    def valueToOSVersionString(self, value):
        """Converts a value to an OS X version number"""
        if isinstance(value, int):
            version_str = hex(value)[2:]
        elif isinstance(value, basestring):
            if value.startswith('0x'):
                version_str = value[2:]
        # OS versions are encoded as hex:
        # 4184 = 0x1058 = 10.5.8
        major = 0
        minor = 0
        patch = 0
        try:
            if len(version_str) == 1:
                major = int(version_str[0])
            if len(version_str) > 1:
                major = int(version_str[0:2])
            if len(version_str) > 2:
                minor = int(version_str[2], 16)
            if len(version_str) > 3:
                patch = int(version_str[3], 16)
        except ValueError:
            raise ProcessorError("Unexpected value in version: %s" % value)
        return "%s.%s.%s" % (major, minor, patch)

    def getInstallerinfo(self):
        """Gets info about an installer from MS metadata."""
        produit = self.env.get("product")
        prod_code = PROD_DICT.get(produit)
        base_url = BASE_URL % (CULTURE_CODE + prod_code)
        version_str = self.env["version"]
        # Get metadata URL
        req = urllib2.Request(base_url)
        # Add the MAU User-Agent, since MAU feed server seems to explicitly block
        # a User-Agent of 'Python-urllib/2.7' - even a blank User-Agent string
        # passes.
        req.add_header("User-Agent",
            "Microsoft%20AutoUpdate/3.0.6 CFNetwork/720.2.4 Darwin/14.4.0 (x86_64)")
        try:
            f = urllib2.urlopen(req)
            data = f.read()
            f.close()
        except BaseException as err:
            raise ProcessorError("Can't download %s: %s" % (base_url, err))

        metadata = plistlib.readPlistFromString(data)
        if version_str == "latest":
            # Still sort by date, in case we should ever need to support
            # fetching versions other than 'latest'.
            sorted_metadata = sorted(metadata, key=itemgetter('Date'))
            # choose the last item, which should be most recent.
            item = sorted_metadata[-1]

        self.env["url"] = item["Location"]
        self.output("Found URL %s" % self.env["url"])
        self.output("Got update: '%s'" % item["Title"])
        # now extract useful info from the rest of the metadata that could
        # be used in a pkginfo
        pkginfo = {}
        # currently ignoring latest dict and cherry-picking en-US, may revisit
        all_localizations = metadata[0].get("Localized")
        pkginfo["description"] = "<html>%s</html>" % all_localizations['1033']['Short Description']
        pkginfo["display_name"] = item["Title"]
        max_os = self.valueToOSVersionString(item['Max OS'])
        min_os = self.valueToOSVersionString(item['Min OS'])
        if max_os != "0.0.0":
            pkginfo["maximum_os_version"] = max_os
        if min_os != "0.0.0":
            pkginfo["minimum_os_version"] = min_os
        installs_items = self.getInstallsItems(item)
        if installs_items:
            pkginfo["installs"] = installs_items
        self.env["version"] = self.getVersion(item)
        self.env["additional_pkginfo"] = pkginfo
        self.env["url"] = item["Location"]
        self.output("Additional pkginfo: %s" % self.env["additional_pkginfo"])

    def main(self):
        """Get information about an update"""
        self.getInstallerinfo()


if __name__ == "__main__":
    processor = MSOffice2016URLandUpdateInfoProvider()
    processor.execute_shell()
