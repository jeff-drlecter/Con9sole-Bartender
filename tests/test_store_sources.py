import copy
import json
from datetime import datetime,timezone
from pathlib import Path
import tempfile
import unittest

from core.store_sources import epic_offers,steam_news,reviewed_steam_offer,StoreNewsStore,combine_articles
from core.rss_preferences import DEFAULT,PreferenceStore
from core.rss_digest import DigestConfig

NOW=2000000000
def iso(t): return datetime.fromtimestamp(t,timezone.utc).isoformat()
def epic_item():
    return dict(title='Example Game',id='abc',status='ACTIVE',offerType='BASE_GAME',
        categories=[{'path':'games/edition/base'}],productSlug='example-game',
        price={'totalPrice':dict(discountPrice=0,originalPrice=1000,voucherDiscount=0,currencyCode='HKD')},
        promotions={'promotionalOffers':[{'promotionalOffers':[dict(startDate=iso(NOW-10),endDate=iso(NOW+100),
            discountSetting=dict(discountType='PERCENTAGE',discountPercentage=0))]}]})
def payload(item): return {'data':{'Catalog':{'searchStore':{'elements':[item]}}}}

class StoreSourcesTests(unittest.TestCase):
    def test_epic_requires_current_base_game_promotion_and_price(self):
        good=epic_item()
        self.assertEqual(len(epic_offers(payload(good),'hk',NOW)),1)
        for key,value in [('offerType','DLC'),('status','INACTIVE')]:
            bad=copy.deepcopy(good);bad[key]=value
            self.assertEqual(epic_offers(payload(bad),'hk',NOW),[])
        for key,value in [('discountPrice',1),('originalPrice',0),('voucherDiscount',1)]:
            bad=copy.deepcopy(good);bad['price']['totalPrice'][key]=value
            self.assertEqual(epic_offers(payload(bad),'hk',NOW),[])
        for key,value in [('startDate',iso(NOW+1)),('endDate',iso(NOW))]:
            bad=copy.deepcopy(good);bad['promotions']['promotionalOffers'][0]['promotionalOffers'][0][key]=value
            self.assertEqual(epic_offers(payload(bad),'hk',NOW),[])
        bad=copy.deepcopy(good);bad['promotions']['promotionalOffers']=[]
        bad['promotions']['upcomingPromotionalOffers']=good['promotions']['promotionalOffers']
        self.assertEqual(epic_offers(payload(bad),'hk',NOW),[])
        bad=copy.deepcopy(good);bad['price']['totalPrice']['currencyCode']='USD'
        with self.assertRaises(ValueError): epic_offers(payload(bad),'hk',NOW)
        with self.assertRaises((KeyError,ValueError)): epic_offers({'data':{}},'hk',NOW)

    def test_region_filter_dedup_and_cross_store_separation(self):
        hk=epic_offers(payload(epic_item()),'hk',NOW)[0]
        tw=copy.deepcopy(hk);tw['offer'].update(region='台灣',regions=['tw'],deadline=NOW+50)
        with tempfile.TemporaryDirectory() as tmp:
            store=StoreNewsStore(Path(tmp)/'news.db')
            store.replace('epic:hk',[hk],NOW)
            store.replace('epic:tw',[tw],NOW)
            pref=dict(DEFAULT,regions=['hk'],platforms=['pc'],stores=['epic'],kinds=['keep'])
            rows=store.preview(DigestConfig(),pref,NOW)
            self.assertEqual(len(rows),1);self.assertEqual(rows[0]['offer']['regions'],['hk'])
            both=combine_articles(store.preview(DigestConfig(),DEFAULT,NOW))
            self.assertEqual(len(both),1);self.assertEqual(both[0]['offer']['deadline'],NOW+50)
            other=copy.deepcopy(hk);other.update(source='steam',link='https://store.steampowered.com/app/1/')
            self.assertEqual(len(combine_articles([hk,other])),2)
            self.assertEqual(store.preview(DigestConfig(exclude_any=['example']),pref,NOW),[])
            self.assertEqual(store.preview(DigestConfig(),pref,NOW+7201),[])
            self.assertEqual(store.batch_report() if hasattr(store,'batch_report') else [],[])
            self.assertEqual(store.report(),[]) # no delivery articles or claims
            reopened=StoreNewsStore(Path(tmp)/'news.db')
            self.assertEqual(len(reopened.preview(DigestConfig(),pref,NOW)),1)
            reopened.replace('epic:hk',[],NOW)
            self.assertEqual(reopened.preview(DigestConfig(),pref,NOW),[])

    def test_legacy_preferences_gain_regions_without_losing_filters(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=PreferenceStore(Path(tmp)/'prefs.db')
            old=dict(DEFAULT,include=['合作']);old.pop('regions')
            with store.connect() as db: db.execute('INSERT INTO preferences VALUES (?,?)',(1,json.dumps(old)))
            current=store.get(1)
            self.assertEqual(current['include'],['合作']);self.assertEqual(current['regions'],['hk','tw'])
            store.put(1,current)
            self.assertEqual(PreferenceStore(Path(tmp)/'prefs.db').get(1),current)

    def test_steam_official_feed_only_and_identity_validation(self):
        row=dict(url='https://store.steampowered.com/news/app/730/view/123',appid=730,gid='123',title='Update',date=NOW,contents='Game update',feedname='steam_community_announcements')
        data={'appnews':dict(appid=730,newsitems=[row])}
        articles=steam_news(data,730,'Game',NOW)
        self.assertEqual(articles[0]['link'],'https://store.steampowered.com/news/app/730/view/123')
        self.assertIsNone(articles[0]['offer'])
        later=dict(articles[0],key='730:456',link='https://store.steampowered.com/news/app/730/view/456')
        self.assertEqual(len(combine_articles(articles+[later])),2)
        row['feedname']='external_news'
        self.assertEqual(steam_news(data,730,'Game',NOW),[])
        data['appnews']['appid']=1
        with self.assertRaises(ValueError): steam_news(data,730,'Game',NOW)

    def test_steam_offers_need_reviewed_evidence_and_live_regional_price(self):
        entry=dict(appid=730,kind='keep',starts_at=iso(NOW-1),ends_at=iso(NOW+100),regions=['hk'],
            evidence_url='https://store.steampowered.com/news/app/730/view/123',reviewed=True)
        app=dict(type='game',steam_appid=730,is_free=False,name='Example',
            price_overview=dict(currency='HKD',initial=1000,final=0,discount_percent=100))
        self.assertIsNotNone(reviewed_steam_offer(entry,app,'hk',NOW))
        self.assertIsNone(reviewed_steam_offer(entry,app,'tw',NOW))
        app['is_free']=True
        self.assertIsNone(reviewed_steam_offer(entry,app,'hk',NOW))
        entry['reviewed']=False
        with self.assertRaises(ValueError):reviewed_steam_offer(entry,app,'hk',NOW)
        entry['reviewed']=True;entry['evidence_url']='https://evil.example/news'
        with self.assertRaises(ValueError):reviewed_steam_offer(entry,app,'hk',NOW)
