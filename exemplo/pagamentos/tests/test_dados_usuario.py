import pytest
import responses
from django.test import Client
from django.urls import reverse
from model_bakery import baker

from django_pagarme import facade
from django_pagarme.models import PagarmeFormConfig, PagarmeItemConfig, PagarmePayment, UserPaymentProfile

TOKEN = 'test_transaction_hfBR0ysHX0NewkUJeXIstI4MdZDb2U'


@pytest.fixture
def payment_config(db):
    return baker.make(
        PagarmeFormConfig,
        max_installments=12,
        free_installment=1,
        interest_rate=1.66,
        payments_methods='boleto'
    )


@pytest.fixture
def payment_item(payment_config):
    return baker.make(
        PagarmeItemConfig,
        tangible=False,
        default_config=payment_config
    )


@pytest.fixture
def pagarme_responses(transaction_json, captured_json):
    with responses.RequestsMock() as rsps:
        rsps.add(responses.GET, f'https://api.pagar.me/1/transactions/{TRANSACTION_ID}', json=transaction_json)
        rsps.add(responses.POST, f'https://api.pagar.me/1/transactions/{TRANSACTION_ID}/capture', json=captured_json)
        yield rsps


@pytest.fixture
def resp_no_user(client, pagarme_responses, payment_item):
    def factory(pagarme_transaction):
        raise facade.ImpossibleUserCreation()

    facade.set_user_factory(factory)
    yield client.get(reverse('django_pagarme:capture', kwargs={'token': TRANSACTION_ID, 'slug': payment_item.slug}))
    facade.set_user_factory(facade._default_factory)


def test_no_user_payment_recording(resp_no_user, logged_user):
    with pytest.raises(facade.UserPaymentProfileDoesNotExist):
        facade.get_user_payment_profile(logged_user)


def test_no_user_payment_relations(resp_no_user, logged_user):
    assert not PagarmePayment.objects.filter(user=logged_user).exists()


@pytest.fixture
def logged_user(django_user_model):
    return baker.make(django_user_model)


@pytest.fixture
def client_with_user(logged_user, client: Client):
    client.force_login(logged_user)
    return client


@pytest.fixture
def resp_with_user(client_with_user, pagarme_responses, payment_item):
    return client_with_user.post(
        reverse('django_pagarme:capture', kwargs={'token': TRANSACTION_ID, 'slug': payment_item.slug}))


def test_logged_user_payment_saved(resp_with_user, logged_user):
    assert facade.get_user_payment_profile(logged_user) is not None


def test_logged_user_payment_relations(resp_with_user, logged_user):
    assert PagarmePayment.objects.filter(user=logged_user).exists()


def test_logged_user_payment_customer_data(resp_with_user, logged_user):
    profile: UserPaymentProfile = facade.get_user_payment_profile(logged_user)
    assert profile.to_customer_dict() == {
        'external_id': str(logged_user.id),
        'type': CUSTOMER_TYPE,
        'country': COSTUMER_COUNTRY,
        'document': {
            'number': DOCUMENT_NUMBER,
            'type': DOCUMENT_TYPE,
        },
        'name': logged_user.first_name,
        'email': logged_user.email,
        'phone': PHONE,
    }


def test_logged_user_card_id(resp_with_user, logged_user):
    profile: UserPaymentProfile = facade.get_user_payment_profile(logged_user)
    assert profile.card_id == CARD_ID


def test_logged_user_payment_billing_address_data(resp_with_user, logged_user):
    profile: UserPaymentProfile = facade.get_user_payment_profile(logged_user)
    assert profile.to_billing_address_dict() == {
        'street': STREET,
        'complementary': COMPLEMENTARY,
        'street_number': STREET_NUMBER,
        'neighborhood': NEIGHBORHOOD,
        'city': CITY,
        'state': STATE,
        'zipcode': ZIPCODE,
        'country': ADDRESS_COUNTRY,
    }


@pytest.fixture
def resp_user_factory(client, pagarme_responses, logged_user, captured_json, transaction_json, payment_item):
    # this user is not logged, will be used as return of factory function
    factory_user = logged_user

    def factory(pagarme_transaction):
        assert pagarme_transaction == transaction_json
        return factory_user

    facade.set_user_factory(factory)

    yield client.get(reverse('django_pagarme:capture', kwargs={'token': TRANSACTION_ID, 'slug': payment_item.slug}))
    # returning factory to original function
    facade._user_factory = facade._default_factory


def test_user_factory_profile_creation(resp_user_factory, logged_user):
    test_logged_user_payment_customer_data(resp_user_factory, logged_user)
    test_logged_user_payment_billing_address_data(resp_user_factory, logged_user)
    test_logged_user_payment_relations(resp_user_factory, logged_user)


@pytest.fixture
def resp_after_first_purchase(client_with_user, pagarme_responses, logged_user, payment_item):
    baker.make(UserPaymentProfile, user_id=logged_user.id, phone='5599888888888')
    return client_with_user.post(
        reverse('django_pagarme:capture', kwargs={'token': TRANSACTION_ID, 'slug': payment_item.slug}))


def test_user_payment_profile_update_with_last_data(resp_after_first_purchase, logged_user):
    test_logged_user_payment_customer_data(resp_after_first_purchase, logged_user)
    test_logged_user_payment_billing_address_data(resp_after_first_purchase, logged_user)


TRANSACTION_ID = 7956027

BOLETO_URL = 'www.some.boleto.com'
BOLETO_BARCODE = '123455'

# Billing Adress Data
STREET = 'Rua Buenos Aires'
COMPLEMENTARY = 'Sem complemento'
STREET_NUMBER = '7'
NEIGHBORHOOD = 'Cidade Vista Verde'
CITY = 'São José dos Campos'
STATE = 'SP'
ZIPCODE = '12223730'
ADDRESS_COUNTRY = 'EN'

# Customer Data
CUSTOMER_TYPE = 'individual'
COSTUMER_COUNTRY = 'br'
DOCUMENT_NUMBER = '123456789'
DOCUMENT_TYPE = 'cpf'
PHONE = '+5512999999999'

CARD_ID = 'card_ck5n7vtbi010or36dojq96sb1'


@pytest.fixture
def transaction_json(payment_item: PagarmeItemConfig, logged_user):
    return {
        'object': 'transaction',
        'status': 'authorized',
        'refuse_reason': None,
        'status_reason': 'acquirer',
        'acquirer_response_code': None,
        'acquirer_name': 'pagarme',
        'acquirer_id': '5cdec7071458b442125d940b',
        'authorization_code': None,
        'soft_descriptor': None,
        'tid': TRANSACTION_ID,
        'nsu': TRANSACTION_ID,
        'date_created': '2020-03-07T17:04:58.279Z',
        'date_updated': '2020-03-07T17:04:58.502Z',
        'authorized_amount': payment_item.price,
        'paid_amount': 0,
        'refunded_amount': 0,
        'installments': 1,
        'id': TRANSACTION_ID,
        'cost': 0,
        'card_holder_name': None,
        'card_last_digits': None,
        'card_first_digits': None,
        'card_brand': None,
        'card_pin_mode': None,
        'card_magstripe_fallback': False,
        'cvm_pin': False,
        'postback_url': 'https://e0f89dca.ngrok.io/django_pagarme/notification',
        'payment_method': 'boleto',
        'capture_method': 'ecommerce',
        'antifraud_score': None,
        'boleto_url': None,
        'boleto_barcode': None,
        'boleto_expiration_date': '2020-03-09T03:00:00.000Z',
        'referer': 'encryption_key',
        'ip': '177.170.213.5',
        'subscription_id': None,
        'phone': None,
        'address': None,
        'customer': {
            'object': 'customer',
            'id': 2725813,
            'external_id': str(logged_user.id),
            'type': CUSTOMER_TYPE,
            'country': COSTUMER_COUNTRY,
            'name': logged_user.first_name,
            'email': logged_user.email,
            'phone_numbers': [PHONE],
            'born_at': None,
            'birthday': None,
            'gender': None,
            'date_created': '2020-03-07T17:04:58.220Z',
            'documents': [
                {
                    'object': 'document',
                    'id': 'doc_ck7huyv07072mmp6f59af8u8h',
                    'type': DOCUMENT_TYPE,
                    'number': DOCUMENT_NUMBER
                }]
        },
        'billing': {
            'address': {
                'street': STREET,
                'complementary': COMPLEMENTARY,
                'street_number': STREET_NUMBER,
                'neighborhood': NEIGHBORHOOD,
                'city': CITY,
                'state': STATE,
                'zipcode': ZIPCODE,
                'country': ADDRESS_COUNTRY,
            }
        },
        'shipping': None,
        'items': [{
            'object': 'item',
            'id': f'{payment_item.slug}',
            'title': f'{payment_item.name}',
            'unit_price': payment_item.price,
            'quantity': 1,
            'category': None,
            'tangible': False,
            'venue': None,
            'date': None
        }],
        'card': {
            'object': 'card', 'id': CARD_ID, 'date_created': '2020-01-21T01:45:57.294Z',
            'date_updated': '2020-01-21T01:45:57.789Z', 'brand': 'visa', 'holder_name': 'agora captura',
            'first_digits': '411111', 'last_digits': '1111', 'country': 'UNITED STATES',
            'fingerprint': 'cj5bw4cio00000j23jx5l60cq', 'valid': True, 'expiration_date': '1227'
        },
        'split_rules': None,
        'metadata': {},
        'antifraud_metadata': {},
        'reference_key': None,
        'device': None,
        'local_transaction_id': None,
        'local_time': None,
        'fraud_covered': False,
        'fraud_reimbursed': None,
        'order_id': None,
        'risk_level': 'unknown',
        'receipt_url': None,
        'payment': None,
        'addition': None,
        'discount': None,
        'private_label': None
    }


@pytest.fixture
def captured_json(payment_item: PagarmeItemConfig, logged_user):
    return {
        'object': 'transaction',
        'status': 'waiting_payment',
        'refuse_reason': None,
        'status_reason': 'acquirer',
        'acquirer_response_code': None,
        'acquirer_name': 'pagarme',
        'acquirer_id': '5cdec7071458b442125d940b',
        'authorization_code': None,
        'soft_descriptor': None,
        'tid': TRANSACTION_ID,
        'nsu': TRANSACTION_ID,
        'date_created': '2020-03-07T17:04:58.279Z',
        'date_updated': '2020-03-07T17:11:14.957Z',
        'amount': payment_item.price,
        'authorized_amount': payment_item.price,
        'paid_amount': 0,
        'refunded_amount': 0,
        'installments': 1,
        'id': TRANSACTION_ID,
        'cost': 0,
        'card_holder_name': None,
        'card_last_digits': None,
        'card_first_digits': None,
        'card_brand': None,
        'card_pin_mode': None,
        'card_magstripe_fallback': False,
        'cvm_pin': False,
        'postback_url': 'https://e0f89dca.ngrok.io/django_pagarme/notification',
        'payment_method': 'boleto',
        'capture_method': 'ecommerce',
        'antifraud_score': None,
        'boleto_url': BOLETO_URL,
        'boleto_barcode': BOLETO_BARCODE,
        'boleto_expiration_date': '2020-03-09T03:00:00.000Z',
        'referer': 'encryption_key',
        'ip': '177.170.213.5',
        'subscription_id': None,
        'phone': None,
        'address': None,
        'customer': {
            'object': 'customer',
            'id': 2725813,
            'external_id': str(logged_user.id),
            'type': CUSTOMER_TYPE,
            'country': COSTUMER_COUNTRY,
            'name': logged_user.first_name,
            'email': logged_user.email,
            'phone_numbers': [PHONE],
            'born_at': None,
            'birthday': None,
            'gender': None,
            'date_created': '2020-03-07T17:04:58.220Z',
            'documents': [
                {
                    'object': 'document',
                    'id': 'doc_ck7huyv07072mmp6f59af8u8h',
                    'type': DOCUMENT_TYPE,
                    'number': DOCUMENT_NUMBER
                }]
        },
        'billing': {
            'address': {
                'street': STREET,
                'complementary': COMPLEMENTARY,
                'street_number': STREET_NUMBER,
                'neighborhood': NEIGHBORHOOD,
                'city': CITY,
                'state': STATE,
                'zipcode': ZIPCODE,
                'country': ADDRESS_COUNTRY,
            }
        },
        'shipping': None,
        'items': [{
            'object': 'item',
            'id': f'{payment_item.slug}',
            'title': f'{payment_item.name}',
            'unit_price': payment_item.price,
            'quantity': 1,
            'category': None,
            'tangible': False,
            'venue': None,
            'date': None
        }],
        'card': {
            'object': 'card', 'id': CARD_ID, 'date_created': '2020-01-21T01:45:57.294Z',
            'date_updated': '2020-01-21T01:45:57.789Z', 'brand': 'visa', 'holder_name': 'agora captura',
            'first_digits': '411111', 'last_digits': '1111', 'country': 'UNITED STATES',
            'fingerprint': 'cj5bw4cio00000j23jx5l60cq', 'valid': True, 'expiration_date': '1227'
        },
        'split_rules': None,
        'metadata': {},
        'antifraud_metadata': {},
        'reference_key': None,
        'device': None,
        'local_transaction_id': None,
        'local_time': None,
        'fraud_covered': False,
        'fraud_reimbursed': None,
        'order_id': None,
        'risk_level': 'unknown',
        'receipt_url': None,
        'payment': None,
        'addition': None,
        'discount': None,
        'private_label': None
    }
