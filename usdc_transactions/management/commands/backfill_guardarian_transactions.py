import logging
import requests
import time
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.conf import settings
from django.utils import timezone
from usdc_transactions.models import GuardarianTransaction, USDCDeposit
from users.models import User

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Backfill Guardarian transactions from specific list of IDs'

    def handle(self, *args, **options):
        self.stdout.write("Starting Guardarian backfill from ID list...")
        
        # provided by user
        ids = [
            '5952424252', '5054126340', '5782944796', '4871013042', '6419415515', '6217313939', '5862189535', 
            '4449421634', '5652018265', '6132501124', '5651156370', '5265022423', '5275501566', '4664255829', 
            '6352898932', '6048382414', '4996500341', '5272487416', '5573962312', '4552841258', '4342393239', 
            '5646121351', '6070905058', '4526237477', '5107016253', '5213512414', '5889245300', '5130987353', 
            '5640278579', '5328120485', '5929419975', '6252308562', '4408906504', '5882230476', '5849605515', 
            '6025430401', '5733925822', '6361173498', '5901757551', '4946957128', '4773946145', '6088879930', 
            '5451592687', '6291625443', '6401489980', '5804903657', '5512227935', '4871273087', '4352302400', 
            '5254590447', '5264231822', '5989263423', '4722246163', '6085068083', '4563385191', '5588955178', 
            '6022680152', '6144052834', '6083507840', '6164832939', '5851879618', '4425565061', '6404354333', 
            '5739176077', '4392153158', '5879809949', '5499292625', '5138111383', '4634856495', '4472839268', 
            '4893383792', '5631387747', '5367679816', '5797391246', '5883391151', '5798255519', '5906194423', 
            '6367809452', '6274493095', '4457645870', '4979560129', '4508967933', '4838027230', '5822639845', 
            '4482826108', '6004878653', '5149845334', '4491981735', '5021710901', '5756699377', '5165298262', 
            '5024216731', '5774392081', '4799691755', '5751328895', '4539176006', '4555958630', '4457974136', 
            '5285105323', '5657928947', '5100153785', '5600669145', '4789398605', '4893796789', '5589313919', 
            '4573431436', '4975187587', '4413811979', '5579759372', '4721872786', '5445978291', '5536613432', 
            '5494896752', '5957947742', '5601390665', '6192910547', '5624855627', '4715993635', '4903151971', 
            '5000278981', '4679991597', '4884428675', '6313959775', '5284253908', '5153182508', '5561197968', 
            '4500052873', '5555369547', '4999694283', '5080905363', '5687502715', '5687809155', '5894198842', 
            '4893922434', '6002654675', '5411974203', '4411757548', '5350712018', '5274739440', '6097102864', 
            '4488772586', '5901478390', '4296898030', '4317871060', '4740488024', '5482904528', '4915223407', 
            '5323385471', '6219387194', '5859836735', '5879985139', '4849889905', '5623260008', '5855982805', 
            '5374175145', '5698383494', '6305307944', '4901456056', '6215989820', '5229318980', '6052709697', 
            '4832773131', '5029973085', '5392006836', '6401124029', '4743190897', '4718679348', '5108999016', 
            '4919608054', '5517757086', '4479219719', '4529334625', '5749225914', '5662247119', '4497890235', 
            '5128814377', '4840124882', '5009840729', '5517158548', '4483411896', '5005801942', '4566488171', 
            '6056203393', '6049068080', '5312363503', '5895828764', '4451932314', '6273764891', '5027011154', 
            '4612690751', '4360653963', '5768828552', '5502158274', '5921719879', '5075919067', '6167592995', 
            '5113206292', '5613381592', '4943186827', '6146903777', '4921182541', '4846405142', '5469656583', 
            '5622491734', '5051140308', '6044778509', '5895820629', '5911093006', '5542398243', '4545277510', 
            '5633164700', '5852325565', '4949761732', '4947144664', '5668674342', '5391587969', '4912213987', 
            '5121969619', '4836053062', '5663964979', '5878606369', '4386023699', '4836783604', '5430328592', 
            '6164273995', '5904624668', '4746529558', '5772442091', '5578577765', '4845864209', '4553640888', 
            '4631234668', '4891821879', '5520315404', '6154644180', '4531368985', '4812101015', '5377684674', 
            '5769036192', '6426393549', '4706660748', '4827378581', '4874155990', '5052097677', '5277076706', 
            '4845895760', '5449947531', '4477012306', '4616132306', '4492464335', '6333564030', '6360974943', 
            '6383922615', '6302786804', '4810996878', '5234801431', '6291761957', '4385462966', '5613922175', 
            '5338683724', '5643159145', '5493803046', '5170580961', '4801027941', '4730778904', '5541634394', 
            '4901085386', '4471379818', '5002931003', '5609339005', '4486190333', '4548973532', '5991548412', 
            '6087554274', '4506101378', '4580230718', '5986244374', '4609978679', '4640575797', '5712048631', 
            '5361369081', '4403485163', '4456834708', '6057266576', '4535470063', '5168023588', '4653313496', 
            '5797305706', '4514107193', '4657745891', '4710826304', '4450066225', '4319476866', '5861126428', 
            '5266266761', '6118176094', '5802098278', '5996149053', '5722078811', '5458923601', '5813232344', 
            '5561747516', '5449907535', '4769295761', '5104203758', '4953913712', '4644324565', '4932884265', 
            '4343064258', '5388180346', '5035933575', '5928214669', '4767747315', '5312051799', '4898688009', 
            '4439501038', '4428884238', '4885518518', '5778656868', '5594239063', '5748229177', '5907642565', 
            '5347174048', '5450126134', '4844094211', '6352881024', '6264005549', '5019477198', '5055789546', 
            '6024014309', '6185093167', '5656685223', '5938305732', '4613362531', '5731517998', '5495522397', 
            '5981632721', '4461570420', '4816588506', '5020070967', '4449655264', '4534985838', '6136478076', 
            '4911021573', '5970346170', '5528174632', '6276974840', '5101544330', '6356625103', '6187153379', 
            '4643627086', '5774789203', '6326927249', '5046423339', '4899622169', '5083242337', '5989155102'
        ]
        
        total = len(ids)
        self.stdout.write(f"Processing {total} transactions...")
        
        updated_count = 0
        
        for idx, g_id in enumerate(ids, 1):
            if idx % 10 == 0:
                self.stdout.write(f"  Progress: {idx}/{total}")
            
            try:
                data = self.fetch_single_transaction(g_id)
                if not data:
                    self.stdout.write(self.style.WARNING(f"  Tx {g_id}: Not found or API error"))
                    continue
                    
                self.process_transaction(data)
                updated_count += 1
                
                # Sleep briefly to avoid rate limits if any
                time.sleep(0.1)
                
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"  Tx {g_id} error: {e}"))

        self.stdout.write(self.style.SUCCESS(f"Backfill complete. Processed {updated_count}/{total} transactions."))

    def fetch_single_transaction(self, g_id):
        api_key = getattr(settings, 'GUARDARIAN_API_KEY', None)
        base_url = getattr(settings, 'GUARDARIAN_API_URL', 'https://api-payments.guardarian.com/v1')
        url = f'{base_url.rstrip("/")}/transaction/{g_id}'
        try:
             resp = requests.get(url, headers={'x-api-key': api_key}, timeout=10)
             if resp.ok:
                 return resp.json()
             else:
                 self.stdout.write(f"  API Error for {g_id}: {resp.status_code}")
        except Exception as e:
             self.stdout.write(f"  Net Error for {g_id}: {e}")
        return None

    def process_transaction(self, data):
        g_id = str(data.get('id'))
        
        tx, created = GuardarianTransaction.objects.get_or_create(
            guardarian_id=g_id,
        )
        
        action = "Created" if created else "Updated"
        
        # Update fields
        tx.status = data.get('status', 'waiting')
        
        if data.get('from_amount'):
            tx.from_amount = Decimal(str(data.get('from_amount')))
        if data.get('to_amount'):
            tx.to_amount_actual = Decimal(str(data.get('to_amount')))
        if data.get('expected_to_amount'):
             tx.to_amount_estimated = Decimal(str(data.get('expected_to_amount')))

        tx.from_currency = data.get('from_currency')
        tx.to_currency = data.get('to_currency')
        tx.network = data.get('to_network')
        
        if data.get('external_partner_link_id'):
            tx.external_id = data.get('external_partner_link_id')

        # Link User
        user_email = data.get('email') or (data.get('customer') or {}).get('contact_info', {}).get('email')
        
        if user_email and not tx.user:
             user = User.objects.filter(email__iexact=user_email).first()
             if user:
                 tx.user = user
        
        # Match OnChain Deposit
        if tx.user and tx.status == 'finished' and not tx.onchain_deposit:
            self.match_onchain_deposit(tx)
            
        if tx.user:
            tx.save()
            self.stdout.write(f"  {action} {g_id}: {tx.status} ({user_email})")
        else:
            self.stdout.write(self.style.WARNING(f"  Skipped {g_id} (No User Matched: {user_email})"))

    def match_onchain_deposit(self, tx):
        candidates = USDCDeposit.objects.filter(
            actor_user=tx.user,
            status='COMPLETED',
            guardarian_source__isnull=True
        ).order_by('-created_at')
        
        matched_dep = None
        
        # Strategy 1: Exact
        if tx.to_amount_actual:
            matched_dep = candidates.filter(amount=tx.to_amount_actual).first()
            
        # Strategy 2: Fuzzy (5%)
        if not matched_dep and tx.to_amount_estimated:
            tolerance = tx.to_amount_estimated * Decimal('0.05')
            for dep in candidates:
                diff = abs(tx.to_amount_estimated - dep.amount)
                if diff <= tolerance:
                    matched_dep = dep
                    break
        
        if matched_dep:
            tx.onchain_deposit = matched_dep
            self.stdout.write(self.style.SUCCESS(f"    Matched Deposit: {matched_dep.deposit_id}"))
