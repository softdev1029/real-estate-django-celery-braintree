def format_telnyx_available_numbers(telnyx_response, return_numbers=False):
    """
    Takes the returned reponse from the Telnyx API `AvailablePhoneNumber.list` and formats it into
    a break down of return area codes and their amounts.

    :param telnyx_response obj: The telnyx API response object.
    :param return_numbers bool: Determines if the returned object should include the phone number
    list.
    """
    area_codes = {}
    phone_numbers = []
    for number in telnyx_response['data']:
        phone = number['phone_number'][2:]  # Remove the '+1'.
        area_code = phone[:3]
        if area_code not in area_codes:
            area_codes[area_code] = 0
        area_codes[area_code] += 1
        phone_numbers.append(phone)

    payload = {
        'area_codes': area_codes,
        'quantity': telnyx_response['metadata']['total_results'],
    }
    if return_numbers:
        payload['phone_numbers'] = phone_numbers

    return payload
