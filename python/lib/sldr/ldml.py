# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
# 1. Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions and the following disclaimer in the
#    documentation and/or other materials provided with the distribution.
# 3. Neither the name of the University nor the names of its contributors
#    may be used to endorse or promote products derived from this software
#    without specific prior written permission.
# 
# THIS SOFTWARE IS PROVIDED BY THE REGENTS AND CONTRIBUTORS ``AS IS'' AND
# ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED.  IN NO EVENT SHALL THE REGENTS OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS
# OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION)
# HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
# LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY
# OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF
# SUCH DAMAGE.

from xml.etree import ElementTree as et
from xml.etree import ElementPath as ep
import re, os, codecs

_elementprotect = {
    '&' : '&amp;',
    '<' : '&lt;',
    '>' : '&gt;' }
_attribprotect = dict(_elementprotect)
_attribprotect['"'] = '&quot;'

class ETWriter(object) :
    """ General purpose ElementTree pretty printer complete with options for attribute order
        beyond simple sorting, and which elements should use cdata """

    nscount = 0

    def __init__(self, et, namespaces = None, attributeOrder = {}, takesCData = set()) :
        self.root = et
        if namespaces is None : namespaces = {}
        self.namespaces = namespaces
        self.attributeOrder = attributeOrder
        self.takesCData = takesCData

    def _localisens(self, tag) :
        if tag[0] == '{' :
            ns, localname = tag[1:].split('}', 1)
            qname = self.namespaces.get(ns, '')
            if qname :
                return ('{}:{}'.format(qname, localname), qname, ns)
            else :
                self.nscount += 1
                return (localname, 'ns_' + str(self.nscount), ns)
        else :
            return (tag, None, None)

    def _protect(self, txt, base=_attribprotect) :
        return re.sub(ur'['+ur"".join(base.keys())+ur"]", lambda m: base[m.group(0)], txt)

    def _nsprotectattribs(self, attribs, localattribs, namespaces) :
        if attribs is not None :
            for k, v in attribs.items() :
                (lt, lq, lns) = self._localisens(k)
                if lns and lns not in namespaces :
                    namespaces[lns] = lq
                    localattribs['xmlns:'+lq] = lns
                localattribs[lt] = v
        

    def serialize_xml(self, write, base = None, indent = '', topns = True, namespaces = {}) :
        """Output the object using write() in a normalised way:
                topns if set puts all namespaces in root element else put them as low as possible"""
        if base is None :
            base = self.root
            write('<?xml version="1.0" encoding="utf-8"?>\n')
        (tag, q, ns) = self._localisens(base.tag)
        localattribs = {}
        if ns and ns not in namespaces :
            namespaces[ns] = q
            localattribs['xmlns:'+q] = ns
        if topns :
            if base == self.root :
                for n,q in self.namespaces.items() :
                    localattribs['xmlns:'+q] = n
                    namespaces[n] = q
        else :
            for c in base :
                (lt, lq, lns) = self._localisens(c.tag)
                if lns and lns not in namespaces :
                    namespaces[lns] = q
                    localattribs['xmlns:'+lq] = lns
        self._nsprotectattribs(getattr(base, 'attrib', None), localattribs, namespaces)
        for c in getattr(base, 'comments', []) :
            write(u'{}<!--{}-->\n'.format(indent, c))
        write(u'{}<{}'.format(indent, tag))
        if len(localattribs) :
            maxAts = len(self.attributeOrder) + 1
            def cmpattrib(x, y) :
                return cmp(self.attributeOrder.get(x, maxAts), self.attributeOrder.get(y, maxAts)) or cmp(x, y)
            for k in sorted(localattribs.keys(), cmp=cmpattrib) :
                write(u' {}="{}"'.format(self._localisens(k)[0], self._protect(localattribs[k])))
        if len(base) :
            write('>\n')
            for b in base :
                self.serialize_xml(write, base=b, indent=indent + "\t", topns=topns, namespaces=namespaces.copy())
            write('{}</{}>\n'.format(indent, tag))
        elif base.text :
            if tag not in self.takesCData :
                t = self._protect(base.text.replace('\n', '\n' + indent), base=_elementprotect)
            else :
                t = "<![CDATA[\n\t" + indent + base.text.replace('\n', '\n\t' + indent) + "\n" + indent + "]]>"
            write(u'>{}</{}>\n'.format(t, tag))
        else :
            write('/>\n')
        for c in getattr(base, 'commentsafter', []) :
            write(u'{}<!--{}-->\n'.format(indent, c))

    def add_namespace(self, q, ns) :
        if ns in self.namespaces : return self.namespaces[ns]
        self.namespaces[ns] = q
        return q

def etwrite(et, write, topns = True, namespaces = None) :
    if namespaces is None : namespaces = {}
    base = ETWriter(et, namespaces)
    base.serialize_xml(write, topns = topns)
    
_alldrafts = ('approved', 'contributed', 'provisional', 'unconfirmed', 'proposed', 'tentative')
_draftratings = dict(map(lambda x: (x[1], x[0]), enumerate(_alldrafts)))

class _arrayDict(dict) :
    def set(self, k, v) :
        if k not in self :
            self[k] = []
        self[k].append(v)

    def pop(self, k, v=None) :
        if k not in self : return v
        res = self[k].pop()
        if not len(self[k]) : del self[k]
        return res

    def remove(self, k, v) :
        if k not in self : return
        self[k].remove(v)
        if not len(self[k]) : del self[k]
        

class _minhash(object) :
    _maxbits = 56
    _bits = 4

    def __init__(self, hasher = hash, nominhash = True) :
        self.minhash = None if nominhash else (1 << self._maxbits) - 1
        self.hashed = 0
        self.hasher = hasher

    def __eq__(self, other) :
        return self.hashed == other.hashed and self.minhash == other.minhash

    def __repr__(self) :
        return "<{} {:0X}>".format(type(self), self.hashed)

    def __hash__(self) :
        return self.hashed

    def update(self, *vec) :
        h = map(self.hasher, vec)
        if self.minhash is not None : map(self._minhashupdate, h)
        self.hashed = reduce(lambda x,y:x * 1000003 + y, h, self.hashed)

    def merge(self, aminh) :
        if self.minhash is not None and aminh.minhash is not None : self._minhashupdate(aminh.minhash)
        self.hashed = self.hashed * 1000003 + aminh.hashed

    def _minhashupdate(self, ahash) :
        x = (1 << self._bits) - 1
        for i in range(self._maxbits / self._bits) :
            if (ahash & x) < (self.minhash & x) :
                self.minhash = (self.minhash & ~x) | (ahash & x)
            x <<= self._bits

    def hamming(self, amin) :
        x = (1 << self._bits) - 1
        res = 0
        for i in range(self._maxbits / self._bits) :
            if (self.minhash & x) != (amin & x) : res += 1
            x <<= self._bits
        return res


class Ldml(ETWriter) :
    takesCData = set(('cr',))
    silns = "urn://www.sil.org/ldml/0.1"

    @classmethod
    def ReadMetadata(cls, fname = None) :
        """Reads supplementalMetadata.xml from CLDR to get useful structural information on LDML"""
        if fname is None :
            fname = os.path.join(os.path.dirname(__file__), 'supplementalMetadata.xml')
        doc = et.parse(fname)
        base = doc.getroot().find('metadata')
        l = base.findtext('attributeOrder').split()
        cls.attributeOrder = dict(zip(l, range(1, len(l) + 1)))
        l = base.findtext('elementOrder').split()
        cls.elementOrder = dict(zip(l, range(1, len(l) + 1)))
        cls.maxEls = len(cls.elementOrder) + 1
        cls.maxAts = len(cls.attributeOrder) + 1
        cls.variables = {}
        for v in base.findall('validity/variable') :
            name = v.get('id')[1:]
            if v.get('type') == 'choice' :
                cls.variables[name] = v.text.split()
            elif v.text :
                cls.variables[name] = v.text.strip()
        cls.blocks = set(base.find('blocking/blockingItems').get('elements', '').split())
        cls.nonkeyContexts = {}         # cls.nonkeyContexts[element] = set(attributes)
        cls.keyContexts = {}            # cls.keyContexts[element] = set(attributes)
        cls.keys = set()
        for e in base.findall('distinguishing/distinguishingItems') :
            if 'elements' in e.attrib :
                if e.get('exclude', 'false') == 'true' :
                    target = cls.nonkeyContexts
                else :
                    target = cls.keyContexts
                localset = set(e.get('attributes').split())
                for a in e.get('elements').split() :
                    if a in target :
                        target[a].update(localset)
                    else :
                        target[a] = set(localset)
            else :
                cls.keys.update(e.get('attributes').split())

    @classmethod
    def ReadSupplementalData(cls, fname = None) :
        """Reads supplementalData.xml from CLDR to get useful structural information on LDML"""
        if fname is None :
            fname = os.path.join(os.path.dirname(__file__), 'supplementalData.xml')
        doc = et.parse(fname)
        cls.parentLocales = {}
        ps = doc.getroot().find('parentLocales')
        for p in ps.findall('parentLocale') :
            parent = p.get('parent')
            for l in p.get('locales').split() :
                if l in cls.parentLocales :
                    cls.parentLocales[l].append(parent)
                else :
                    cls.parentLocales[l] = [parent]
        cls.languageInfo = {}
        ps = doc.getroot().find('languageData')
        for p in ps.findall('language') :
            ss = []; ts = []
            if p.get('type') in cls.languageInfo :
                ss, ts = cls.languageInfo[p.get('type')]
            if p.get('scripts') :
                ss += p.get('scripts').split(' ')
            if p.get('territories') :
                ts += p.get('territories').split(' ')
            cls.languageInfo[p.get('type')] = [ss, ts]

    @classmethod
    def ReadLikelySubtags(cls, fname = None) :
        """Reads the likely subtag mappings"""
        if fname is None :
            fname = os.path.join(os.path.dirname(__file__), 'likelySubtags.xml')
        doc = et.parse(fname)
        cls.likelySubtags = {}
        ps = doc.getroot().find('likelySubtags')
        for p in ps.findall('likelySubtag') :
            cls.likelySubtags[p.get('from')] = p.get('to')

    def __init__(self, fname, usedrafts=True) :
        if not hasattr(self, 'elementOrder') :
            self.__class__.ReadMetadata()
        self.fname = fname
        self.namespaces = {}
        self.useDrafts = usedrafts
        fh = open(self.fname, 'rb')     # expat does utf-8 decoding itself. Don't do it twice
        curr = None
        comments = []
        parser = et.XMLParser(target=et.TreeBuilder(), encoding="UTF-8")
        def doComment(data) :
            # resubmit as new start tag=! and sort out in main loop
            parser.parser.StartElementHandler("!--", ('text', data))
            parser.parser.EndElementHandler("!--")
        parser.parser.CommentHandler = doComment
        for event, elem in et.iterparse(fh, events=('start', 'start-ns', 'end'), parser=parser) :
            if event == 'start-ns' :
                self.namespaces[elem[1]] = elem[0]
            elif event == 'start' :
                elem.document = self
                if elem.tag == '!--' :
                    comments.append(elem.get('text'))
                else :
                    if len(comments) :
                        elem.comments = comments
                        comments = []
                    if curr is not None :
                        elem.parent = curr
                    else :
                        self.root = elem
                    curr = elem
            elif elem.tag == '!--' :
                if curr is not None :
                    curr.remove(elem)
            else :
                if len(comments) and len(elem) :
                    elem[-1].commentsafter = comments
                    comments = []
                curr = getattr(elem, 'parent', None)
        fh.close()
        self.analyse()
        self.normalise(self.root, usedrafts=usedrafts)

    def copynode(self, n, parent=None) :
        res = n.copy()
        for a in ('contentHash', 'attrHash', 'comments', 'commentsafter', 'parent', 'document') :
            if hasattr(n, a) :
                setattr(res, a, getattr(n, a, None))
        if parent is not None :
            res.parent = parent
        return res

    def get_parent_locales(self, name) :
        if not hasattr(self, 'parentLocales') :
            self.__class__.ReadSupplementalData()
        fall = self.root.find('fallback')
        if fall is not None :
            return fall.split()
        elif name in self.parentLocales :
            return self.parentLocales[name]
        else :
            return []

    def normalise(self, base=None, addguids=True, usedrafts=False) :
        """Normalise according to LDML rules"""
        if base is None :
            base = self.root
        if len(base) :
            for b in base :
                self.normalise(b, addguids=addguids, usedrafts=usedrafts)
            def cmpat(x, y) :
                return cmp(self.attributeOrder.get(x, self.maxAts), self.attributeOrder.get(y, self.maxAts)) or cmp(x, y)
            def cmpel(x, y) :   # order by elementOrder and within that attributes in attributeOrder
                res = cmp(self.elementOrder.get(x.tag, self.maxEls), self.elementOrder.get(y.tag, self.maxEls) or cmp(x.tag, y.tag))
                if res != 0 : return res
                xl = sorted(x.keys(), cmp=cmpat)
                yl = sorted(y.keys(), cmp=cmpat)
                for i in range(len(xl)) :
                    if i >= len(yl) : return -1
                    res = cmp(x.get(xl[i]), y.get(yl[i]))
                    if res != 0 : return res
                if len(yl) > len(xl) : return 1
                return 0
            children = sorted(base, cmp=cmpel) if base.tag not in self.blocks else list(base)
            base[:] = children
        if base.text :
            t = base.text.strip()
            base.text = re.sub(ur'\s*\n\s*', '\n', t)           # content hash has text in lines
        base.tail = None
        if usedrafts or addguids :
            self._calc_hashes(base, usedrafts=usedrafts)
        if usedrafts :                                          # pack up all alternates
            temp = {}
            for c in base :
                a = c.get('alt', None)
                if a is None or a.find("proposed") == -1 :
                    temp[c.attrHash] = c
            tbase = list(base)
            for c in tbase :
                a = c.get('alt', '')
                if a.find("proposed") != -1 and c.attrHash in temp :
                    a = re.sub(ur"proposed.*$", "", a)
                    t = temp[c.attrHash]
                    if not hasattr(t, 'alternates') :
                        t.alternates = {}
                    t.alternates[a] = c
                    base.remove(c)

    def analyse(self, usedrafts=False) :
        identity = self.root.find('./identity/special/{' + self.silns + '}identity')
        if identity is not None:
            self.default_draft = _draftratings.get(identity.get('draft', 'proposed'))
            self.uid = identity.get('uid', None)
        else :
            self.default_draft = _draftratings['proposed']
            self.uid = None

    def _calc_hashes(self, base, usedrafts=False) :
        base.contentHash = _minhash(nominhash = True)
        for b in base :
            base.contentHash.merge(b.contentHash)
        if base.text : base.contentHash.update(*(base.text.split("\n")))
        distkeys = set(self.keys)
        if base.tag in self.nonkeyContexts :
            distkeys -= self.nonkeyContexts[base.tag]
        if usedrafts :
            distkeys.discard('draft')
        base.attrHash = _minhash(nominhash = True)
        base.attrHash.update(base.tag)                      # keying hash has tag
        for k in sorted(base.keys()) :                      # any consistent order is fine
            if usedrafts and k == 'alt' and base.get(k).find("proposed") == -1 :
                val = re.sub(ur"proposed.*$", "", base.get(k))
                base.attrHash.update(k, val)
            elif k in distkeys :
                base.attrHash.update(k, base.get(k))        # keying hash has key attributes
            elif not usedrafts or (k != 'draft' and k != 'alt' and k != '{'+self.silns+'}alias') :
                base.contentHash.update(k, base.get(k))     # content hash has non key attributes
        base.contentHash.merge(base.attrHash)               #   and keying hash

    def serialize_xml(self, write, base = None, indent = '', topns = True, namespaces = {}) :
#        if base is None and self.useDrafts :
#            self.namespaces[self.silns] = 'sil'
        if self.useDrafts :
            n = base if base is not None else self.root
            offset = 0
            alt = n.get('alt', '')
            for (i, c) in enumerate(list(n)) :
                if not hasattr(c, 'alternates') : continue
                for a in sorted(c.alternates.keys()) :
                    c.alternates[a].set('alt', alt+a)
                    offset += 1
                    n.insert(i + offset, c.alternates[a])
                    c.alternates[a].tempnode = True
        super(Ldml, self).serialize_xml(write, base, indent, topns, namespaces)
        if self.useDrafts :
            n = base if base is not None else self.root
            for c in list(n) :
                if hasattr(c, 'tempnode') and c.tempnode :
                    n.remove(c)

    def get_modified_draft(self, e, default=None) :
        ldraft = e.get('draft', None)
        if ldraft is not None : return _draftratings.get(ldraft, 5)
        return _draftratings.get(default, e.document.default_draft)

    def overlay(self, other, usedrafts=False, this=None, odraft='', tdraft='') :
        """Add missing information in self from other. Honours @draft attributes"""
        if this == None : this = self.root
        other = getattr(other, 'root', other)
        if usedrafts :
            tdraft = this.get('draft', tdraft)
            odraft = other.get('draft', odraft)
        for o in other :
            addme = True
            for t in filter(lambda x: x.attrHash == o.attrHash, this) :
                addme = False
                if o.contentHash != t.contentHash :
                    if o.tag not in self.blocks :
                        self.overlay(o, usedrafts=usedrafts, this=t, odraft=odraft, tdraft=tdraft)
                    elif usedrafts :
                        self._merge_leaf(other, t, o)
                break  # only do one alignment
            if addme and (o.tag != "alias" or not len(this)) :  # alias in effect turns it into blocking
                this.append(o)

    def _merge_leaf(self, other, b, o) :
        """Handle @draft and @alt"""
        if not hasattr(o, 'alternates') : return
        if hasattr(b, 'alternates') :
            for (k, v) in o.items() :
                if k not in b.alternates : b.alternates[k] = v
        else :
            b.alternates = o.alternates
            
    def resolve_aliases(self, this=None) :
        if this is None : this = self.root
        hasalias = False
        for (i, c) in enumerate(list(this)) :
            if c.tag == 'alias' :
                v = c.get('path', None)
                if v is None : continue
                this.remove(c)
                count = 1
                for res in this.findall(v + "/*") :
                    res = self.copynode(res, parent=this)
                    self.resolve_aliases(res)
                    # res.set('{'+self.silns+'}alias', "1")
                    # self.namespaces[self.silns] = 'sil'
                    this.insert(i+count, res)
                    count += 1
                hasalias = True
            else :
                hasalias |= self.resolve_aliases(c)
        if hasalias and self.useDrafts :
            self._calc_hashes(this)
            return True
        return False

    def difference(self, other, this=None) :
        """Strip out everything that is in other, from self, so long as the values are the same."""
        if this == None : this = self.root
        other = getattr(other, 'root', other)
        # if empty elements, test .text and all the attributes
        if not len(other) and not len(this) :
            return (other.contentHash == this.contentHash)
        for o in other :
            for t in filter(lambda x: x.attrHash == o.attrHash, this) :
                if o.contentHash == t.contentHash or (o.tag not in self.blocks and self.difference(o, this=t)) :
                    if hasattr(t, 'alternates') and hasattr(o, 'alternates') :
                        for (k, v) in o.alternates :
                            if k in t.alternates and v.contentHash == t.alternates[k].contentHash :
                                del t.alternates[k]
                        if len(t.alternates) == 0 :
                            this.remove(t)
                    else :
                        this.remove(t)
                break
        return not len(this) and (not this.text or this.text == other.text)

    def _align(self, this, other, base) :
        """Internal method to merge() that aligns elements in base and other to this and
           records the results in this. O(7N)"""
        olist = dict(map(lambda x: (x.contentHash, x), other))
        if base is not None : blist = dict(map(lambda x: (x.contentHash, x), base))
        for t in list(this) :
            t.mergeOther = olist.get(t.contentHash, None)
            t.mergeBase = blist.get(t.contentHash, None) if base is not None else None
            if t.mergeOther is not None :
                del olist[t.contentHash]
                if t.mergeBase is not None :
                    del blist[t.contentHash]
            elif t.mergeBase is not None :
                del blist[t.contentHash]
        odict = _arrayDict()
        for v in olist.values() : odict.set(v.attrHash, v)
        if base is not None :
            bdict = _arrayDict()
            for v in blist.values() : bdict.set(v.attrHash, v)
        for t in filter(lambda x: x.mergeOther == None, this) :     # go over everything not yet associated
            # this is pretty horrible - find first alignment on key attributes. (sufficient for ldml)
            t.mergeOther = odict.pop(t.attrHash)
            if t.mergeOther is not None :
                del olist[t.mergeOther.contentHash]
                if t.mergeBase is None and base is not None :
                    if t.mergeOther.contentHash in blist :
                        t.mergeBase = blist.pop(t.mergeOther.contentHash)
                        bdict.remove(t.mergeBase.attrHash, t.mergeBase)
                    else :
                        t.mergeBase = bdict.pop(t.attrHash)
                        if t.mergeBase is not None : del blist[t.mergeBase.contentHash]
            elif t.mergeBase is not None :
                this.remove(t)
        for e in olist.values() :       # pick up stuff in other but not in this
            if base is None or e.contentHash in blist :
                this.append(e)
                e.mergeOther = None     # don't do anything with this in merge()

    def _merge_with_alts(self, base, other, target, default='proposed', copycomments=None) :
        """3-way merge the alternates putting the results in target. Assumes target content is the required ending content"""
        if base.contentHash != target.contentHash and (base.text or base.tag in self.blocks) and self.get_draft(base) < self.get_draft(target, default) :
            self._add_alt(target, target, default=default)
            target[:] = base
            for a in ('text', 'contentHash', 'comments', 'commentsafter') :
                setattr(target, a, getattr(base, a, None))
            if 'alt' in target.attrib :
                del target.attrib['alt']
            if self.get_draft(base) != target.document.default_draft :
                target.set('draft', _alldrafts[self.get_draft(base)])
        elif copycomments is not None :
            for a in ('comments', 'commentsafter') :
                setattr(target, a, getattr((base if copycomments =='base' else other), a))
        temp = base.get('{'+self.silns+'}alias', '')
        if temp :
            target.set('{'+self.silns+'}alias', '1')
        self._merge_alts(base, other, target, default)

    def _merge_alts(self, base, other, target, default='propose') :
        if other is None or not hasattr(other, 'alternates') : return
        if not hasattr(target, 'alternates') :
            target.alternates = dict(other.alternates)
            return
        if base is None : return
        balt = getattr(base, 'alternates', {})
        allkeys = set(balt.keys() + target.alternates + other.alternates)
        for k in allkeys :
            if k not in balt :
                if k not in other.alternates : continue
                if k not in target.alternates or self.get_draft(target.alternates[k], default) > self.get_draft(other.alternates, default) :
                    target.alternates[k] = other.alternates[k]
            elif k not in other.alternates :
                if k not in target.alternates or self.get_draft(target.alternates[k], default) > self.get_draft(balt[k]) :
                    target.alternates[k] = balt[k]
            elif k not in target.alternates :
                if k not in other.alternates or self.get_draft(other.alternates[k], default) > self.get_draft(balt[k]) :
                    target.alternates[k] = balt[k]
                else :
                    target.alternates[k] = other.alternates[k]
            elif self.get_draft(target.alternates[k], default) > self.get_draft(other.alternates[k], default) :
                target.alternates[k] = other.alternates[k]
            elif self.get_draft(target.alternates[k], default) > self.get_draft(balt[k]) :
                target.alternates[k] = balt[k]
            elif other.alternates[k].contentHash != balt[k].contentHash :
                target.alternates[k] = other.alternates[k]
        return

    def _add_alt(self, target, origin, default='proposed') :
        odraft = self.get_draft(origin, default)
        if hasattr(origin.document, 'uid') and origin.document.uid is not None :
            alt = 'proposed-' + origin.document.uid
        else :
            alt = 'proposed'
        if hasattr(target, 'alternates') and alt in target.alternates :
            v = target.alternates[alt]
            if self.get_draft(v, default) >= odraft :
                if origin.contentHash is None :
                    del target.alternates[alt]
                else :
                    target.alternates[alt] = origin.copy()
                    origin.set('alt', alt)
        elif origin.contentHash is not None :
            if not hasattr(target, 'alternates') :
                target.alternates = {}
            target.alternates[alt] = origin.copy()
            target.alternates[alt].set('alt', alt)

    def merge(self, other, base, this=None, default=None, copycomments=None) :
        """Does 3 way merging of self/this and other against a common base. O(N)"""
        if this == None : this = self.root
        if hasattr(other, 'root') : other = other.root
        if hasattr(base, 'root') : base = base.root
        self._align(this, other, base)
        for t in list(this) :                                   # go through our children merging them
            if t.mergeOther is not None and t.mergeOther.contentHash != t.contentHash :     # other differs
                if t.mergeBase is not None and t.mergeBase.contentHash == t.contentHash :   # base doesn't
                    if self.useDrafts :
                        self._merge_with_alts(t.mergeBase, t.mergeOther, t, default=default, copycomments=copycomments)
                    else :
                        this.remove(t)                                  # swap us out
                        this.append(t.mergeOther)
                elif t.mergeBase is not None and t.mergeBase.contentHash != t.mergeOther.contentHash :
                    self.merge(t.mergeOther, t.mergeBase, t)        # could be a clash so recurse
            elif self.useDrafts and t.mergeBase is not None :
                self._merge_alts(t.mergeBase, t.mergeOther, t, default=default, copycomments=copycomments)
        if base is not None and this.text == base.text :
            if other is not None:
                this.text = other.text
                this.contentHash = other.contentHash
            else :
                this.text = None
                this.contentHash = None
            if self.useDrafts : self._merge_with_alts(base, other, this, default=default, copycomments=copycomments)
        elif other is not None and other.text != base.text :
            self.clash_text(this.text, other.text, (base.text if base is not None else None),
                                        this, other, base, usedrafts=self.useDrafts)
            if self.useDrafts :
                self._merge_with_alts(base, other, this)
                return
        oattrs = set(other.keys())
        for k in this.keys() :                                  # go through our attributes
            if k in oattrs :
                if base is not None and k in base.attrib and base.get(k) == this.get(k) and this.get(k) != other.get(k) :
                    this.set(k, other.get(k))                       # t == b && t != o
                elif this.get(k) != other.get(k) :
                    self.clash_attrib(k, this.get(k), other.get(k), base.get(k), this, other, base, usedrafts=self.useDrafts)    # t != o
                oattrs.remove(k)
            elif base and k in base.attrib :                        # o deleted it
                this.attrib.pop(k)
        for k in oattrs :                                       # attributes in o not in t
            if base is None or k not in base.attrib or base.get(k) != other.get(k) :
                this.set(k, other.get(k))                           # if new in o or o changed it and we deleted it

    def clash_text(self, ttext, otext, btext, this, other, base, usedrafts = False, default=None) :
        if usedrafts :
            bdraft = self.get_draft(base)
            tdraft = self.get_draft(this)
            odraft = self.get_draft(other)
            if tdraft < odraft :
                self._add_alt(this, other, default=default)
                return
            elif odraft < tdraft :
                self._add_alt(this, this, default=default)
                this.text = otext
                this.contentHash = other.contentHash
                return
            elif tdraft >= bdraft :
                self._add_alt(this, this, default=default)
                self._add_alt(this, other, default=default)
                this.text = btext
                this.contentHash = base.contentHash
                return
        if not hasattr(this, 'comments') : this.comments = []
        this.comments.append('Clash: "{}" or "{}" from "{}"'.format(ttext, otext, btext))

    def clash_attrib(self, key, tval, oval, bval, this, other, base, usedrafts = False) :
        if not hasattr(this, 'comments') : this.comments = []
        this.comments.append('Attribute ({}) clash: "{}" or "{}" from "{}"'.format(key, tval, oval, bval))
        return tval        # not sure what to do here. 'We' win!

    def get_script(self, name) :
        """Analyses the language name and code and anything it can find to identify the script for this file"""
        start = name.find('_')
        if start > 0 :
            end = name[start+1:].find('_')
            if end < 0 :
                end = len(name)
            else :
                end += start + 1
            if (end - start) == 5 :
                return name[start+1:end]
        l = self.root.find('identity/language')
        if l is not None :
            lang = l.get('type')
        else :
            lang = name
        scripts = []
        if not hasattr(self, 'languageInfo') : self.__class__.ReadSupplementalData()
        if lang in self.languageInfo :
            scripts = self.languageInfo[lang][0]
            if len(scripts) == 1 : return scripts[0]
        if not hasattr(self, 'likelySubtags') : self.__class__.ReadLikelySubtags()
        if lang in self.likelySubtags :
            return self.likelySubtags[lang].split('_')[1]
        return None

    def remove_private(self) :
        """ Remove private elements and return them as a list of elements """
        res = []
        if self.root is None : return res
        for n in ('contacts', 'comments') :
            for e in self.root.findall(n) :
                res.append(e)
                self.root.remove(e)
                e.parent = None
        return res

    def add_id(self, **attrs) :
        """Inserts identity/special/sil:identity/@revid"""
        i = self.root.find('identity')
        if i is not None :
            s = i.find('special/{'+self.silns+'}identity')
            if s is None :
                se = et.SubElement(i, 'special')
                if 'sil' not in self.namespaces :
                    self.namespaces[self.silns] = 'sil'
                s = et.SubElement(se, '{'+self.silns+'}identity')
            for (k, v) in attrs.items() :
                s.set(k, v)

def _prepare_parent(next, token) :
    def select(context, result) :
        for elem in result :
            if hasattr(elem, 'parent') :
                yield elem.parent
    return select
ep.ops['..'] = _prepare_parent


def flattenlocale(lname, dirs=[], rev='f', changed=set(), autoidentity=True, skipstubs=False) :
    """ Flattens an ldml file by filling in missing details from the fallback chain.
        If rev true, then do the opposite and unflatten a flat LDML file by removing
        everything that is the same in the fallback chain.
        changed contains an optional set of locales that if present says that the operation
        is only applied if one or more of the fallback locales are in the changed set.
        autoidentity says to insert or remove script information from the identity element."""
    def trimtag(s) :
        r = s.rfind('_')
        if r < 0 :
            return ''
        else :
            return s[:r]

    def getldml(lname, dirs) :
        for d in dirs :
            f = os.path.join(d, lname + '.xml')
            if os.path.exists(f) :
                return Ldml(f)
            f = os.path.join(d, lname[0].lower(), lname + '.xml')
            if os.path.exists(f) :
                return Ldml(f)
        return None

    if not isinstance(lname, Ldml) :
        l = getldml(lname, dirs)
    else :
        l = lname
    if l is None : return l
    if skipstubs and len(l.root) == 1 and l.root[0].tag == 'identity' : return None
    if rev != 'c' :
        fallbacks = l.get_parent_locales(lname)
        if not len(fallbacks) :
            fallbacks = [trimtag(lname)]
        if 'root' not in fallbacks and lname != 'root' :
            fallbacks += ['root']
        if len(changed) :       # check against changed
            dome = False
            for f in fallbacks :
                if f in changed :
                    dome = True
                    break
            if not dome : return None
        dome = True
        for f in fallbacks :    # apply each fallback
            while len(f) :
                o = getldml(f, dirs)
                if o is not None :
                    if rev == 'r' :
                        l.difference(o)
                        dome = False
                        break   # only need one for unflatten
                    else :
                        l.overlay(o)
                f = trimtag(f)
            if not dome : break
    if skipstubs and len(l.root) == 1 and l.root[0].tag == 'identity' : return None
    if autoidentity :
        i = l.root.find('identity')
        if i is not None :
            s = l.get_script(lname)
            if s and rev != 'r' and i.find('script') is None :
                se = et.SubElement(i, "script", type=s)
            elif s and rev == 'r' :
                se = i.find('script')
                if se is not None and se.get('type') == s :
                    i.remove(se)
    return l

if __name__ == '__main__' :
    import sys, codecs
    l = Ldml(sys.argv[1])
    if len(sys.argv) > 2 :
        for f in sys.argv[2:] :
            if f.startswith('-') :
                o = Ldml(f[1:])
                l.difference(o)
            else :
                o = Ldml(f)
                l.overlay(o)
    l.normalise()
    sys.stdout = codecs.getwriter('UTF-8')(sys.stdout)
    l.serialize_xml(sys.stdout.write) #, topns=False)

