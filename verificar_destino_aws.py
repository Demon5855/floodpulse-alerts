"""
Verifica un numero de destino en el sandbox de AWS SNS SMS.
Paso obligatorio mientras la cuenta este en sandbox: sin esto, AWS acepta
el publish() pero descarta el SMS despues, sin avisar en la respuesta.

Uso (dos pasos, se corre dos veces):

1) python verificar_destino_aws.py solicitar +593963000180
   -> Te llega un SMS con un codigo de 6 digitos al numero.

2) python verificar_destino_aws.py confirmar +593963000180 123456
   -> Con el codigo que recibiste, completa la verificacion.
"""

import os
import sys

import boto3
from dotenv import load_dotenv

load_dotenv()

cliente = boto3.client(
    "sns",
    region_name=os.getenv("AWS_REGION", "us-east-1"),
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
)

accion = sys.argv[1] if len(sys.argv) > 1 else None

if accion == "solicitar" and len(sys.argv) == 3:
    numero = sys.argv[2]
    resp = cliente.create_sms_sandbox_phone_number(PhoneNumber=numero)
    print(f"Codigo de verificacion enviado a {numero}. Revisa el celular.")

elif accion == "confirmar" and len(sys.argv) == 4:
    numero, codigo = sys.argv[2], sys.argv[3]
    cliente.verify_sms_sandbox_phone_number(PhoneNumber=numero, OneTimePassword=codigo)
    print(f"{numero} verificado. Ya puedes enviarle SMS por AWS.")

elif accion == "listar":
    resp = cliente.list_sms_sandbox_phone_numbers()
    for n in resp.get("PhoneNumbers", []):
        print(f"  {n['PhoneNumber']:20} {n['Status']}")

else:
    print(__doc__)
